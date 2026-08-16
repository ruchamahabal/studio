import { call } from "frappe-ui"
import { ref, type Ref } from "vue"
import { type AIChatHandlers, attachAIChatListeners, detachAIChatListeners } from "@/components/ai/realtime"
import { ToolDispatcher } from "@/components/ai/toolDispatch"
import type { BlockOptions } from "@/types"
import { tryParseJsonBlock } from "@/utils/blockCodec"
import { throttle } from "@/utils/helpers"

/** Everything the controller needs from the panel: the shared chat state it mutates
 * and the canvas/page helpers it drives. Keeps the controller free of Vue component
 * internals so the agent turn lifecycle lives in one testable place. */
export interface AIChatContext {
	socket: any
	messages: Ref<any[]>
	loading: Ref<boolean>
	statusMessage: Ref<string>
	error: Ref<string>
	pageId: () => string
	getCanvas: () => any
	getPageContext: () => string
	getSelectedBlockIds: () => string[]
	setRootBlock: (block: BlockOptions) => void
	/** The server persisted the OPEN page's draft (agent write) — sync the editor's
	 * timestamp/draft marker so the user's next manual save doesn't conflict. */
	syncPersistedPage: (modified?: string) => void
	reloadSession: () => void
	scrollToBottom: () => void
	reloadPageData: (opts: {
		resources?: boolean
		variables?: boolean
		script?: boolean
		modified?: string
	}) => void
}

/**
 * Orchestrates one Studio AI agent turn: sends the user prompt to
 * `studio.ai.api.run` and reacts to the `ai_chat_*` realtime events (keyed by
 * session, so the turn keeps streaming across page navigation). The server
 * applies and persists every op to its TARGET page; the canvas here only
 * mirrors ops whose target is the page currently open. Block-tree mutation
 * lives in ToolDispatcher; full-page generation streams as `page_json`.
 */
export class AIChatController {
	sessionId = ref("")
	// Optional screenshot/design attached to the next prompt (base64 data URL) — reproduced as a layout.
	imageData = ref<string | null>(null)
	imagePreviewUrl = ref<string | null>(null)
	imageFileName = ref("")
	// The running turn's live timeline (ai_chat_step, upserted by id) and the pages
	// it created/updated (ai_chat_page). Cleared when the turn ends — the persisted
	// copies come back on the final message via reloadSession.
	steps = ref<any[]>([])
	pageEvents = ref<any[]>([])
	private readonly dispatcher: ToolDispatcher
	private pendingAssistantId: number | null = null
	private summary = ""
	private pageBuffer = ""
	private readonly renderStreamedPage: () => void

	constructor(private readonly ctx: AIChatContext) {
		this.dispatcher = new ToolDispatcher({ getCanvas: ctx.getCanvas, setRootBlock: ctx.setRootBlock })
		// Re-parsing + rebuilding the whole tree per token pegs the CPU; the final
		// generate_page op re-applies the authoritative document, so a coarse cadence is fine.
		this.renderStreamedPage = throttle(() => {
			const block = tryParseJsonBlock(this.pageBuffer)
			if (block) this.ctx.setRootBlock(block)
		}, 200)
	}

	get handlers(): AIChatHandlers {
		return {
			onProgress: this.onProgress,
			onStream: this.onStream,
			onStep: this.onStep,
			onToolBatch: this.onToolBatch,
			onPage: this.onPage,
			onClarify: this.onClarify,
			onComplete: this.onComplete,
			onError: this.onError,
			onReload: this.onReload,
		}
	}

	attach(channel: string) {
		attachAIChatListeners(this.ctx.socket, channel, this.handlers)
	}

	detach(channel: string) {
		detachAIChatListeners(this.ctx.socket, channel, this.handlers)
	}

	/** Whether an incoming canvas op targets the page open in the editor. Ops for
	 * any other page were already persisted server-side — mirroring them here would
	 * paint them onto the wrong canvas (the original cross-page bug). */
	private targetsOpenPage(data: any): boolean {
		return !data.target_page_id || data.target_page_id === this.ctx.pageId()
	}

	async submit(promptText: string, model: string) {
		this.summary = ""
		this.pageBuffer = ""
		this.steps.value = []
		this.pageEvents.value = []
		this.ctx.error.value = ""
		this.ctx.loading.value = true
		this.ctx.statusMessage.value = ""
		const image = this.imageData.value
		this.pushMessage("user", promptText, image ? { attachedImageUrl: image } : undefined)
		this.clearImage()
		this.pendingAssistantId = this.pushMessage("assistant", "Thinking…")
		this.ctx.scrollToBottom()
		try {
			const res: any = await call("studio.ai.api.run", {
				prompt: promptText,
				page_id: this.ctx.pageId(),
				session_id: this.sessionId.value || undefined,
				page_context: this.ctx.getPageContext(),
				model,
				selected_block_ids: this.ctx.getSelectedBlockIds(),
				image_data: image ?? undefined,
			})
			if (res?.session_id) this.sessionId.value = res.session_id
			if (res?.status === "busy") {
				this.onError({ message: res.message || "Another AI request is still processing." })
			}
		} catch (e: any) {
			this.onError({ message: e?.message || "Failed to start. Please try again." })
		}
	}

	/** Apply or skip a confirm-gated action the agent proposed (Apply/Skip card). */
	async confirmPending(messageId: string, apply: boolean) {
		this.ctx.loading.value = true
		try {
			const res: any = await call("studio.ai.api.confirm_pending_action", {
				session_id: this.sessionId.value,
				message_id: messageId,
				apply,
			})
			if (res?.messages) this.ctx.messages.value = res.messages
		} catch (e: any) {
			this.ctx.error.value = e?.message || "Could not apply the action."
		} finally {
			this.ctx.loading.value = false
			this.ctx.scrollToBottom()
		}
	}

	/** Undo an AI turn: restore the page from its snapshot and rewind the chat. */
	async revertTo(messageId: string) {
		try {
			const res: any = await call("studio.ai.api.revert_to_message", {
				session_id: this.sessionId.value,
				message_id: messageId,
			})
			if (res?.messages) this.ctx.messages.value = res.messages
		} catch (e: any) {
			this.ctx.error.value = e?.message || "Could not revert."
		}
	}

	cancel = async () => {
		if (!this.sessionId.value) return
		this.ctx.statusMessage.value = "Cancelling…"
		try {
			await call("studio.ai.api.cancel", { session_id: this.sessionId.value })
		} catch {
			// Ignore — the user will see the cancelled event when it arrives.
		}
	}

	// --- realtime handlers ------------------------------------------------

	onProgress = (data: any) => {
		this.ctx.loading.value = true
		this.ctx.statusMessage.value = data.message || this.ctx.statusMessage.value
	}

	onStream = (data: any) => {
		if (!data.chunk) return
		if (data.kind === "page_json") {
			// A generation for a page open elsewhere still streams (progress lives in
			// the timeline) but must not paint THIS canvas.
			if (!this.targetsOpenPage(data)) return
			this.pageBuffer += data.chunk
			this.renderStreamedPage()
			return
		}
		this.summary += data.chunk
		this.updatePending(this.summary)
		this.ctx.scrollToBottom()
	}

	onStep = (data: any) => {
		// The same step id arrives twice (running, then done) — upsert by id.
		const index = this.steps.value.findIndex((s) => s.id === data.id)
		const step = { ...data }
		delete step.page_id
		delete step.target_page_id
		if (index === -1) this.steps.value = [...this.steps.value, step]
		else {
			const next = [...this.steps.value]
			next[index] = step
			this.steps.value = next
		}
		this.ctx.scrollToBottom()
	}

	onPage = (data: any) => {
		// The server saved this page's draft. If it's the page open in the editor,
		// sync the stamp so the user's next save doesn't hit a timestamp conflict.
		if (data.action === "updated" && data.name && data.name === this.ctx.pageId()) {
			this.ctx.syncPersistedPage(data.modified)
		}
		this.pageEvents.value = [
			...this.pageEvents.value.filter((p) => p.name !== data.name),
			{ action: data.action, name: data.name, title: data.title, route: data.route },
		]
	}

	onToolBatch = (data: any) => {
		if (!data.operations?.length) return
		// The server already applied + persisted these ops on their target page.
		// Mirror them here only when that page is the one on screen.
		if (!this.targetsOpenPage(data)) return
		this.dispatcher.applyToolBatch(data.operations)
		this.ctx.scrollToBottom()
	}

	onComplete = (data: any) => {
		this.ctx.loading.value = false
		this.ctx.statusMessage.value = ""
		this.updatePending(this.summary || data.message || "Done")
		this.pendingAssistantId = null
		this.summary = ""
		this.pageBuffer = ""
		this.steps.value = []
		this.pageEvents.value = []
		this.ctx.reloadSession()
	}

	onError = (data: any) => {
		this.ctx.loading.value = false
		this.ctx.statusMessage.value = ""
		this.ctx.error.value = data.message || "Request failed."
		this.pendingAssistantId = null
		this.summary = ""
		this.pageBuffer = ""
		this.steps.value = []
		this.pageEvents.value = []
		this.ctx.reloadSession()
	}

	onReload = (data: any) => {
		// A server tool wrote page data (data sources / variables / script). Re-fetch so the
		// canvas re-evaluates `{{ }}` bindings and re-runs setup() against the live state.
		if (!this.targetsOpenPage(data)) return
		this.ctx.reloadPageData({
			resources: !!data.resources,
			variables: !!data.variables,
			script: !!data.script,
			modified: data.modified,
		})
	}

	onClarify = (data: any) => {
		this.ctx.loading.value = false
		this.ctx.statusMessage.value = ""
		if (data.plan_summary) {
			this.updatePending(data.headline || "Here's my plan", {
				status: "plan_summary",
				headline: data.headline || "",
				data_plan: data.data_plan || [],
				layout_plan: data.layout_plan || [],
				palette: data.palette || "",
			})
		} else if (data.pending_action) {
			this.updatePending(data.question || "Apply this change?", {
				status: "pending_action",
				pending_action: data.pending_action,
			})
		} else {
			this.updatePending(data.question || "Could you clarify?", {
				status: "clarification",
				options: data.options || [],
			})
		}
		this.pendingAssistantId = null
		this.summary = ""
		this.steps.value = []
		this.pageEvents.value = []
		// Backend persists+commits clarify messages before emitting, so this is race-free.
		this.ctx.reloadSession()
	}

	// --- helpers ----------------------------------------------------------

	private pushMessage(
		role: "user" | "assistant",
		content: string,
		metadata?: Record<string, any>,
	): number {
		const id = Date.now() + this.ctx.messages.value.length
		this.ctx.messages.value = [...this.ctx.messages.value, { id, role, content, ...(metadata ? { metadata } : {}) }]
		return id
	}

	attachImageFile = (file: File) => {
		if (!file.type.startsWith("image/")) return
		if (file.size > 5 * 1024 * 1024) {
			this.ctx.error.value = "Image is too large. Please use an image smaller than 5 MB."
			return
		}
		this.imageFileName.value = file.name || "pasted-image.png"
		const reader = new FileReader()
		reader.onload = (e) => {
			this.imageData.value = e.target?.result as string
			this.imagePreviewUrl.value = this.imageData.value
		}
		reader.readAsDataURL(file)
	}

	clearImage = () => {
		this.imageData.value = null
		this.imagePreviewUrl.value = null
		this.imageFileName.value = ""
	}

	private updatePending(content: string, metadata?: Record<string, any>) {
		if (this.pendingAssistantId == null) return
		const index = this.ctx.messages.value.findIndex((m) => m.id === this.pendingAssistantId)
		if (index === -1) return
		const next = [...this.ctx.messages.value]
		next[index] = {
			...next[index],
			content,
			...(metadata ? { metadata: { ...next[index].metadata, ...metadata } } : {}),
		}
		this.ctx.messages.value = next
	}
}
