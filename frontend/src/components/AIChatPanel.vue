<template>
	<div class="flex flex-1 flex-col overflow-hidden bg-surface-base">
		<div
			class="flex shrink-0 items-center justify-between border-b border-outline-gray-1 bg-surface-base px-3 py-2.5"
		>
			<Popover placement="bottom-start" :offset="6">
				<template #target="{ togglePopover }">
					<button
						class="flex max-w-[11rem] items-center gap-1 truncate text-[11px] leading-4 text-ink-gray-5 hover:text-ink-gray-8"
						title="Switch chat"
						@click="loadSessions(togglePopover)"
					>
						<span class="truncate">{{ sessionTitle || "Chat" }}</span>
						<FeatherIcon name="chevron-down" class="h-3 w-3 shrink-0" />
					</button>
				</template>
				<template #body="{ close }">
					<div
						class="max-h-64 min-w-52 overflow-y-auto rounded-lg border border-outline-gray-2 bg-surface-base py-1 shadow-lg"
					>
						<button
							class="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium text-ink-gray-8 hover:bg-surface-gray-2"
							@click="newSession(close)"
						>
							<FeatherIcon name="plus" class="h-3 w-3" />
							New chat
						</button>
						<button
							v-for="s in sessions"
							:key="s.name"
							class="flex w-full flex-col px-3 py-1.5 text-left hover:bg-surface-gray-2"
							:class="{ 'bg-surface-gray-1': s.name === sessionId }"
							@click="switchSession(s.name, close)"
						>
							<span class="truncate text-xs text-ink-gray-8">{{ s.title || "Untitled chat" }}</span>
							<span class="text-[10px] text-ink-gray-4">{{ s.last_interaction_on }}</span>
						</button>
					</div>
				</template>
			</Popover>
			<button
				v-if="messages.length"
				class="text-xs text-ink-gray-4 hover:text-ink-gray-9"
				@click="clearSession"
			>
				Clear
			</button>
		</div>

		<div v-if="!isAIEnabled" class="flex flex-1 flex-col items-start gap-3 p-4">
			<p class="text-p-xs text-ink-gray-6">
				Configure an AI API key in Studio Settings to use the AI assistant.
			</p>
			<Button variant="subtle" label="Open Settings" @click="store.showStudioSettingsDialog = true" />
		</div>

		<div v-else ref="messagesEl" class="no-scrollbar flex-1 space-y-4 overflow-y-auto px-4 py-4">
			<div
				v-if="!messages.length"
				class="flex h-full flex-col items-center justify-center gap-2 pb-8 text-center"
			>
				<LucideSparkle class="h-8 w-8 text-ink-gray-3" />
				<p class="text-xs text-ink-gray-4">Chat to create or edit this page</p>
			</div>

			<template v-for="msg in messages" :key="msg.id">
				<div v-if="msg.role === 'user'" class="flex flex-col items-end gap-1">
					<img
						v-if="msg.metadata?.attachedImageUrl"
						:src="msg.metadata.attachedImageUrl"
						class="max-h-40 max-w-[88%] rounded-md border border-outline-gray-2 object-contain"
						alt="Attached design"
					/>
					<div
						v-if="msg.content"
						class="w-fit max-w-[88%] rounded-md border bg-surface-gray-1 px-3 py-2 text-p-xs text-ink-gray-8"
					>
						<div class="whitespace-pre-wrap break-words">{{ msg.content }}</div>
					</div>
				</div>
				<div v-else class="flex w-full flex-col items-start gap-2">
					<!-- Persisted turn timeline (what the agent did), collapsed by default -->
					<details v-if="msg.metadata?.steps?.length" class="w-full">
						<summary class="cursor-pointer select-none text-[11px] text-ink-gray-4 hover:text-ink-gray-6">
							Worked through {{ msg.metadata.steps.length }} step{{
								msg.metadata.steps.length === 1 ? "" : "s"
							}}
						</summary>
						<AITurnTimeline :steps="msg.metadata.steps" class="mt-1.5" />
					</details>

					<div
						class="w-fit max-w-full break-words text-p-xs text-ink-gray-8 [&_a]:text-ink-blue-3 [&_a]:underline [&_code]:rounded [&_code]:bg-surface-gray-2 [&_code]:px-1 [&_code]:py-0.5 [&_h1]:my-1.5 [&_h1]:text-sm [&_h1]:font-semibold [&_h2]:my-1.5 [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:my-0.5 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1 [&_pre]:my-1 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-surface-gray-2 [&_pre]:p-2 [&_strong]:font-semibold [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5"
						v-html="renderMarkdown(msg.content)"
					/>

					<!-- Pages this turn created/updated — open them in the editor -->
					<div v-if="otherPages(msg.metadata?.pages).length" class="flex flex-wrap gap-1.5">
						<button
							v-for="page in otherPages(msg.metadata?.pages)"
							:key="page.name"
							class="flex items-center gap-1 rounded-md border border-outline-gray-2 bg-surface-gray-1 px-2 py-1 text-[11px] text-ink-gray-7 hover:bg-surface-gray-2"
							:title="page.route"
							@click="openPage(page)"
						>
							<FeatherIcon name="file" class="h-3 w-3 text-ink-gray-4" />
							{{ page.title || page.name }}
							<FeatherIcon name="arrow-up-right" class="h-3 w-3 text-ink-gray-4" />
						</button>
					</div>

					<!-- Undo this turn's changes -->
					<button
						v-if="msg.metadata?.revertSnapshot && msg.id === lastMessageId && !loading"
						class="flex items-center gap-1 text-[11px] text-ink-gray-4 hover:text-ink-gray-8"
						@click="revertTurn(msg)"
					>
						<FeatherIcon name="rotate-ccw" class="h-3 w-3" />
						Undo this change
					</button>

					<!-- Confirm-gated action: Apply / Skip -->
					<div
						v-if="msg.metadata?.status === 'pending_action' && msg.id === lastMessageId"
						class="flex gap-1.5"
					>
						<Button
							variant="solid"
							size="sm"
							label="Apply"
							:disabled="loading"
							@click="controller.confirmPending(String(msg.id), true)"
						/>
						<Button
							variant="outline"
							size="sm"
							label="Skip"
							:disabled="loading"
							@click="controller.confirmPending(String(msg.id), false)"
						/>
					</div>

					<!-- Proposed plan: data plan + layout plan + palette + approve -->
					<div
						v-if="msg.metadata?.status === 'plan_summary'"
						class="flex w-full min-w-0 flex-col gap-3 rounded-md border border-outline-gray-1 bg-surface-gray-1 p-3"
					>
						<div v-if="msg.metadata.data_plan?.length" class="flex flex-col gap-1">
							<div class="text-[10px] font-semibold uppercase tracking-wide text-ink-gray-5">Data</div>
							<ul class="flex flex-col gap-1">
								<li
									v-for="(item, i) in msg.metadata.data_plan"
									:key="'d' + i"
									class="break-words text-p-xs text-ink-gray-7"
								>
									• {{ item }}
								</li>
							</ul>
						</div>
						<div v-if="msg.metadata.layout_plan?.length" class="flex flex-col gap-1">
							<div class="text-[10px] font-semibold uppercase tracking-wide text-ink-gray-5">Layout</div>
							<ul class="flex flex-col gap-1">
								<li
									v-for="(item, i) in msg.metadata.layout_plan"
									:key="'l' + i"
									class="break-words text-p-xs text-ink-gray-7"
								>
									• {{ item }}
								</li>
							</ul>
						</div>
						<div v-if="msg.metadata.palette" class="break-words text-[11px] text-ink-gray-5">
							Palette: {{ msg.metadata.palette }}
						</div>
						<Button
							v-if="msg.id === lastMessageId"
							variant="outline"
							size="sm"
							label="Approve & build"
							:disabled="loading"
							@click="sendPrompt('Yes, that looks good - go ahead and build it.')"
						/>
					</div>

					<!-- Clarification: tappable answer options -->
					<div
						v-else-if="
							msg.metadata?.status === 'clarification' &&
							msg.metadata.options?.length &&
							msg.id === lastMessageId
						"
						class="flex flex-wrap gap-1.5"
					>
						<Button
							v-for="(option, i) in msg.metadata.options"
							:key="i"
							variant="outline"
							size="sm"
							:label="option"
							:disabled="loading"
							@click="sendPrompt(option)"
						/>
					</div>
				</div>
			</template>

			<!-- Live turn: the steps streaming in right now, then the status line -->
			<div v-if="loading" class="flex flex-col gap-2">
				<AITurnTimeline :steps="liveSteps" />
				<div v-if="otherPages(livePages).length" class="flex flex-wrap gap-1.5">
					<button
						v-for="page in otherPages(livePages)"
						:key="page.name"
						class="flex items-center gap-1 rounded-md border border-outline-gray-2 bg-surface-gray-1 px-2 py-1 text-[11px] text-ink-gray-7 hover:bg-surface-gray-2"
						@click="openPage(page)"
					>
						<FeatherIcon name="file" class="h-3 w-3 text-ink-gray-4" />
						{{ page.title || page.name }}
						<FeatherIcon name="arrow-up-right" class="h-3 w-3 text-ink-gray-4" />
					</button>
				</div>
				<p class="text-p-xs text-ink-gray-5">{{ statusMessage || "Generating…" }}</p>
			</div>
		</div>

		<div v-if="isAIEnabled" class="shrink-0 border-t border-outline-gray-1 bg-surface-base p-4">
			<ErrorMessage v-if="error" :message="error" class="mb-2" />

			<div v-if="isModifyMode" class="mb-2 flex items-center gap-1.5 rounded py-1">
				<span class="truncate text-xs text-ink-gray-5">Editing:</span>
				<Badge variant="subtle" size="sm">
					{{ selectedBlock?.blockName || selectedBlock?.componentName }}
				</Badge>
			</div>

			<div v-if="imagePreviewUrl" class="mb-2 flex items-center gap-2">
				<div class="relative">
					<img
						:src="imagePreviewUrl"
						class="h-12 w-12 rounded border border-outline-gray-2 object-cover"
						alt="Attached design"
					/>
					<button
						class="text-ink-white absolute -right-1.5 -top-1.5 rounded-full bg-surface-gray-7 p-0.5 hover:bg-surface-gray-6"
						title="Remove image"
						@click="controller.clearImage()"
					>
						<FeatherIcon name="x" class="h-3 w-3" />
					</button>
				</div>
				<span class="truncate text-xs text-ink-gray-5">{{ imageFileName }}</span>
			</div>

			<div class="relative">
				<textarea
					v-model="prompt"
					rows="4"
					class="w-full resize-none rounded border border-[--surface-gray-2] bg-surface-gray-2 px-2 py-1.5 text-p-sm text-ink-gray-8 placeholder-ink-gray-4 transition-colors hover:border-[--outline-elevation-2] hover:bg-surface-gray-3 focus:border-outline-gray-4 focus:bg-surface-base focus:shadow-sm focus:ring-0 focus-visible:ring-2 focus-visible:ring-outline-gray-3 disabled:cursor-not-allowed disabled:bg-surface-gray-1 disabled:text-ink-gray-5"
					:placeholder="
						isModifyMode ? 'Describe what to change in this block...' : 'Chat to create or edit this page...'
					"
					:disabled="loading"
					@keydown.meta.enter="generate"
					@keydown.ctrl.enter="generate"
					@paste="onPaste"
					@drop="onDropImage"
					@dragover.prevent
				/>
			</div>

			<div class="mt-2 flex items-center justify-between gap-2">
				<div class="flex items-center gap-0.5">
					<Popover placement="top-start" :offset="6">
						<template #target="{ togglePopover }">
							<button
								class="flex h-7 max-w-[9rem] items-center gap-1.5 rounded px-1.5 text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-8"
								@click="togglePopover"
							>
								<FeatherIcon name="cpu" class="h-3.5 w-3.5 shrink-0" />
								<span class="truncate text-xs">{{ modelLabel }}</span>
							</button>
						</template>
						<template #body="{ close }">
							<div class="min-w-40 rounded-lg border border-outline-gray-2 bg-surface-base py-1 shadow-lg">
								<button
									v-for="option in modelOptions"
									:key="option.value"
									class="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm text-ink-gray-7 hover:bg-surface-gray-2"
									:class="{ 'font-medium text-ink-gray-9': option.value === selectedModel }"
									@click="
										() => {
											selectedModel = option.value
											close()
										}
									"
								>
									<span>{{ option.label }}</span>
									<FeatherIcon
										v-if="option.vision"
										name="image"
										class="h-3.5 w-3.5 shrink-0 text-ink-gray-4"
										title="Supports image attachments"
									/>
								</button>
							</div>
						</template>
					</Popover>

					<button
						v-if="isVisionModel"
						class="flex h-7 items-center gap-1.5 rounded px-1.5 text-ink-gray-5 transition-colors hover:bg-surface-gray-2 hover:text-ink-gray-8 disabled:cursor-not-allowed disabled:opacity-50"
						title="Attach a screenshot or design to reproduce"
						:disabled="loading"
						@click="imageInput?.click()"
					>
						<FeatherIcon name="image" class="h-3.5 w-3.5 shrink-0" />
					</button>
					<input ref="imageInput" type="file" accept="image/*" class="hidden" @change="onImageSelected" />
				</div>

				<Button v-if="loading" variant="subtle" label="Stop" icon="square" @click="stop" />
				<Button
					v-else
					variant="solid"
					:label="isModifyMode ? 'Edit' : 'Generate'"
					icon="arrow-up"
					:disabled="!prompt.trim() && !imagePreviewUrl"
					@click="generate"
				/>
			</div>
		</div>
	</div>
</template>

<script lang="ts" setup>
import { ref, computed, inject, watch, nextTick, onUnmounted } from "vue"
import { useRouter } from "vue-router"
import { ErrorMessage, Button, Badge, FeatherIcon, call, createResource, Popover, toast } from "frappe-ui"
import { marked } from "marked"
import DOMPurify from "dompurify"
import useStudioStore from "@/stores/studioStore"
import useCanvasStore from "@/stores/canvasStore"
import useCodeStore from "@/stores/codeStore"
import { AIChatController } from "@/components/AIChatController"
import AITurnTimeline from "@/components/ai/AITurnTimeline.vue"
import { getBlockInstance, getBlockString } from "@/utils/serializer"
import type { BlockOptions } from "@/types"
import { studioSettings } from "@/data/studioSettings"
import LucideSparkle from "~icons/lucide/sparkle"

const store = useStudioStore()
const canvasStore = useCanvasStore()
const codeStore = useCodeStore()
const socket = inject<any>("socket")
const router = useRouter()

const isAIEnabled = computed(() => !!studioSettings.doc?.ai_api_key)

const prompt = ref("")
const loading = ref(false)
const error = ref("")
const statusMessage = ref("")
const selectedModel = ref("")
const messages = ref<any[]>([])
const messagesEl = ref<HTMLElement | null>(null)

// A plan's "Approve & build" and a clarification's options only make sense for the CURRENT turn —
// the last message. On older ones they're stale (already answered), so gate the buttons on this.
const lastMessageId = computed(() => messages.value[messages.value.length - 1]?.id)

const pageId = computed(() => store.activePage?.name ?? "")

const selectedBlock = computed(() => {
	const block = canvasStore.activeCanvas?.selectedBlocks?.[0] ?? null
	if (!block || block.isRoot()) return null
	return block
})

const isModifyMode = computed(() => !!selectedBlock.value)

const aiModels = createResource({
	url: "studio.ai.models.get_ai_models",
	auto: true,
})

const modelOptions = computed(() =>
	(aiModels.data ?? []).map((m: any) => ({ label: m.label, value: m.id, vision: !!m.vision_capable })),
)

const modelLabel = computed(() => {
	const selected = modelOptions.value.find((m: any) => m.value === selectedModel.value)
	return selected ? selected.label : "Model"
})

const isVisionModel = computed(() => {
	const selected = modelOptions.value.find((m: any) => m.value === selectedModel.value)
	return selected ? selected.vision : true
})

const sessionTitle = ref("")
const sessions = ref<any[]>([])
// The app whose session is loaded — navigation within the same app keeps the
// session (and its running turn) untouched.
const loadedAppId = ref("")

const sessionResource = createResource({
	url: "studio.ai.api.get_ai_session",
	onSuccess(data: any) {
		messages.value = data.messages ?? []
		controller.sessionId.value = data.session_id ?? ""
		sessionTitle.value = data.title ?? ""
		loadedAppId.value = data.app ?? ""
		if (data.selected_model) {
			selectedModel.value = data.selected_model
		} else if (modelOptions.value.length) {
			selectedModel.value = modelOptions.value[0].value
		}
		scrollToBottom()
	},
})

const appId = computed(() => store.activePage?.studio_app ?? "")

async function loadSessions(toggle: () => void) {
	toggle()
	if (!appId.value) return
	sessions.value = (await call("studio.ai.api.list_ai_sessions", { app_id: appId.value })) ?? []
}

function switchSession(sessionId: string, close: () => void) {
	close()
	sessionResource.submit({ session_id: sessionId })
}

async function newSession(close: () => void) {
	close()
	if (!appId.value) return
	const data: any = await call("studio.ai.api.new_ai_session", {
		app_id: appId.value,
		page_id: pageId.value,
		model: selectedModel.value,
	})
	controller.sessionId.value = data?.session_id ?? ""
	loadedAppId.value = data?.app ?? appId.value
	sessionTitle.value = ""
	messages.value = []
}

function otherPages(pages: any[] | undefined): any[] {
	// A chip for the page already on screen is noise (opening it is a no-op).
	return (pages ?? []).filter((p) => p.name !== pageId.value)
}

function openPage(page: { name: string }) {
	if (!page?.name || page.name === pageId.value) return
	router.push({ name: "StudioPage", params: { appID: appId.value, pageID: page.name } })
}

async function revertTurn(msg: any) {
	if (!confirm("Undo this change? The page goes back to how it was before this turn.")) return
	await controller.revertTo(String(msg.id))
	store.activePage && store.setPage(store.activePage.name)
}

function scrollToBottom() {
	nextTick(() => {
		if (messagesEl.value) {
			messagesEl.value.scrollTo({
				top: messagesEl.value.scrollHeight,
				behavior: "smooth",
			})
		}
	})
}

function reloadSession() {
	// Reload the SAME session (not the page's latest) — after a turn ends the panel
	// may be on another page of the app.
	if (controller.sessionId.value) {
		sessionResource.submit({ session_id: controller.sessionId.value })
	} else if (pageId.value) {
		sessionResource.submit({ page_id: pageId.value })
	}
}

function renderMarkdown(content: string): string {
	if (!content) return ""
	return DOMPurify.sanitize(marked.parse(content, { gfm: true, breaks: true }) as string)
}

function getPageContext() {
	const root = store.pageBlocks?.[0] ?? canvasStore.activeCanvas?.getRootBlock()
	return root ? getBlockString(root) : "[]"
}

const controller = new AIChatController({
	socket,
	messages,
	loading,
	statusMessage,
	error,
	pageId: () => pageId.value,
	getCanvas: () => canvasStore.activeCanvas,
	getPageContext,
	getSelectedBlockIds: () => (selectedBlock.value ? [selectedBlock.value.componentId] : []),
	setRootBlock: (block: BlockOptions) => {
		const rootBlock = getBlockInstance(block)
		store.pageBlocks = [rootBlock]
		canvasStore.activeCanvas?.setRootBlock(rootBlock, false)
	},
	syncPersistedPage: (modified?: string) => {
		// The agent saved this page's draft server-side; adopt its timestamp so the
		// user's next manual save doesn't hit a conflict, and mark the draft state
		// for the publish indicator.
		store.syncPageModified({ modified })
		if (store.activePage) store.activePage.draft_blocks = getPageContext()
	},
	reloadSession,
	scrollToBottom,
	reloadPageData: ({ resources, variables, script, modified }) => {
		const page = store.activePage
		if (!page) return
		if (resources) codeStore.setPageResources(page)
		if (variables) codeStore.setPageVariables(page)
		if (script) store.reloadActivePageScript()
		store.syncPageModified({ modified })
	},
})

// Live turn state (streamed steps + page chips + session id), exposed for the template.
const liveSteps = controller.steps
const livePages = controller.pageEvents
const sessionId = controller.sessionId

watch(isVisionModel, (vision) => {
	if (!vision) controller.clearImage()
})

// Attached-image state + input (exposed so the template auto-unwraps the refs).
const imagePreviewUrl = controller.imagePreviewUrl
const imageFileName = controller.imageFileName
const imageInput = ref<HTMLInputElement | null>(null)

function onImageSelected(e: Event) {
	const input = e.target as HTMLInputElement
	const file = input.files?.[0]
	if (file) controller.attachImageFile(file)
	input.value = "" // let the same file be re-picked
}

function onPaste(e: ClipboardEvent) {
	const file = Array.from(e.clipboardData?.items || [])
		.find((item) => item.type.startsWith("image/"))
		?.getAsFile()
	if (!file) return
	e.preventDefault()
	if (!warnIfNoVision()) return
	controller.attachImageFile(file)
}

function onDropImage(e: DragEvent) {
	const file = e.dataTransfer?.files?.[0]
	if (!file?.type.startsWith("image/")) return
	e.preventDefault()
	if (!warnIfNoVision()) return
	controller.attachImageFile(file)
}

function warnIfNoVision(): boolean {
	if (isVisionModel.value) return true
	toast.error(`${modelLabel.value} can't read images. Pick a vision-capable model to attach a design.`)
	return false
}

// Realtime listeners are keyed by SESSION, not page: a running turn keeps
// streaming into this panel across page navigation, and the canvas mirror is
// gated per-event by target_page_id (see AIChatController.onToolBatch).
let attachedChannel = ""
function ensureListeners() {
	if (!socket) return
	const channel = controller.sessionId.value
	if (channel === attachedChannel) return
	if (attachedChannel) controller.detach(attachedChannel)
	if (channel) controller.attach(channel)
	attachedChannel = channel
}
watch(() => controller.sessionId.value, ensureListeners)
onUnmounted(() => {
	if (attachedChannel) controller.detach(attachedChannel)
})

watch(
	() => pageId.value,
	(newId) => {
		if (!newId) return
		// Same app → same session: keep the chat (and any running turn) untouched.
		if (controller.sessionId.value && loadedAppId.value && loadedAppId.value === appId.value) return
		sessionResource.submit({ page_id: newId })
	},
	{ immediate: true },
)

async function generate() {
	const text = prompt.value.trim()
	const hasImage = !!controller.imageData.value
	if (!text && !hasImage) return
	prompt.value = ""
	// An attached design with no words is still a valid instruction: reproduce it.
	await controller.submit(text || "Reproduce this attached design as a page.", selectedModel.value)
}

function stop() {
	controller.cancel()
}

// A clarification option or plan approval is just the user's next message.
function sendPrompt(text: string) {
	if (loading.value) return
	controller.submit(text, selectedModel.value)
}

async function clearSession() {
	await call("studio.ai.api.clear_ai_session", {
		session_id: controller.sessionId.value || undefined,
		page_id: pageId.value,
	})
	messages.value = []
}
</script>
