import { call } from "frappe-ui"
import { ref, type Ref } from "vue"
import { type AIChatHandlers, attachAIChatListeners, detachAIChatListeners } from "@/components/ai/realtime"
import { ToolDispatcher } from "@/components/ai/toolDispatch"
import type { BlockOptions } from "@/types"
import { tryParseJsonBlock } from "@/utils/blockCodec"
import { captureRenderedPage, getImageWidth } from "@/utils/captureCanvas"
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
	savePage: () => void
	reloadSession: () => void
	scrollToBottom: () => void
	reloadPageData: (opts: { resources?: boolean; variables?: boolean; script?: boolean }) => void
}

/**
 * Orchestrates one Studio AI agent turn: sends the user prompt to
 * `studio.ai.api.run` and reacts to the `ai_chat_*` realtime events. Block-tree
 * mutation lives in ToolDispatcher; full-page generation streams as `page_json`.
 */
export class AIChatController {
	sessionId = ""
	// Optional screenshot/design attached to the next prompt (base64 data URL) — reproduced as a layout.
	imageData = ref<string | null>(null)
	imagePreviewUrl = ref<string | null>(null)
	imageFileName = ref("")
	// The last design submitted with a prompt — kept after submit so "Refine to match design"
	// can re-send it alongside a fresh capture of the current render.
	designReference = ref<string | null>(null)
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
			onToolBatch: this.onToolBatch,
			onClarify: this.onClarify,
			onComplete: this.onComplete,
			onError: this.onError,
			onReload: this.onReload,
		}
	}

	attach(pageId: string) {
		attachAIChatListeners(this.ctx.socket, pageId, this.handlers)
	}

	detach(pageId: string) {
		detachAIChatListeners(this.ctx.socket, pageId, this.handlers)
	}

	async submit(promptText: string, model: string) {
		this.beginTurn()
		const image = this.imageData.value
		if (image) this.designReference.value = image
		this.pushMessage("user", promptText, image ? { attachedImageUrl: image } : undefined)
		this.clearImage()
		this.pendingAssistantId = this.pushMessage("assistant", "Thinking…")
		this.ctx.scrollToBottom()
		await this.dispatchRun({ prompt: promptText, model, image_data: image ?? undefined })
	}

	/** Visual feedback loop: capture the current render at the design's resolution and send
	 * both images so the model lists the discrepancies and fixes them with targeted edits. */
	refineToMatchDesign = async (model: string) => {
		const design = this.designReference.value
		if (!design || this.ctx.loading.value) return
		this.beginTurn()
		this.ctx.statusMessage.value = "Capturing the current render…"
		const render = await captureRenderedPage((await getImageWidth(design)) ?? undefined)
		if (!render) {
			this.ctx.loading.value = false
			this.ctx.statusMessage.value = ""
			this.ctx.error.value = "Could not capture the current render."
			return
		}
		const promptText = "Refine the page to match the attached target design."
		this.pushMessage("user", promptText)
		this.pendingAssistantId = this.pushMessage("assistant", "Comparing the render against the design…")
		this.ctx.scrollToBottom()
		await this.dispatchRun({
			prompt: promptText,
			model,
			// A refine turn compares whole pages — a lingering block selection must not scope it.
			selected_block_ids: [],
			images: [
				{ label: "TARGET DESIGN", data: design },
				{ label: "CURRENT RENDER", data: render },
			],
		})
	}

	private beginTurn() {
		this.summary = ""
		this.pageBuffer = ""
		this.ctx.error.value = ""
		this.ctx.loading.value = true
		this.ctx.statusMessage.value = ""
	}

	private async dispatchRun(params: Record<string, any>) {
		try {
			const res: any = await call("studio.ai.api.run", {
				page_id: this.ctx.pageId(),
				page_context: this.ctx.getPageContext(),
				selected_block_ids: this.ctx.getSelectedBlockIds(),
				...params,
			})
			if (res?.session_id) this.sessionId = res.session_id
			if (res?.status === "busy") {
				this.onError({ message: res.message || "Another AI request is still processing." })
			}
		} catch (e: any) {
			this.onError({ message: e?.message || "Failed to start. Please try again." })
		}
	}

	cancel = async () => {
		if (!this.sessionId) return
		this.ctx.statusMessage.value = "Cancelling…"
		try {
			await call("studio.ai.api.cancel", { session_id: this.sessionId })
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
			this.pageBuffer += data.chunk
			this.renderStreamedPage()
			return
		}
		this.summary += data.chunk
		this.updatePending(this.summary)
		this.ctx.scrollToBottom()
	}

	onToolBatch = (data: any) => {
		if (!data.operations?.length) return
		this.dispatcher.applyToolBatch(data.operations)
		this.ctx.savePage()
		this.ctx.scrollToBottom()
	}

	onComplete = (data: any) => {
		this.ctx.loading.value = false
		this.ctx.statusMessage.value = ""
		this.updatePending(this.summary || data.message || "Done")
		this.pendingAssistantId = null
		this.summary = ""
		this.pageBuffer = ""
		this.ctx.reloadSession()
	}

	onError = (data: any) => {
		this.ctx.loading.value = false
		this.ctx.statusMessage.value = ""
		this.ctx.error.value = data.message || "Request failed."
		this.pendingAssistantId = null
		this.summary = ""
		this.pageBuffer = ""
		this.ctx.reloadSession()
	}

	onReload = (data: any) => {
		// A server tool wrote page data (data sources / variables / script). Re-fetch so the
		// canvas re-evaluates `{{ }}` bindings and re-runs setup() against the live state.
		this.ctx.reloadPageData({
			resources: !!data.resources,
			variables: !!data.variables,
			script: !!data.script,
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
		} else {
			this.updatePending(data.question || "Could you clarify?", {
				status: "clarification",
				options: data.options || [],
			})
		}
		this.pendingAssistantId = null
		this.summary = ""
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
