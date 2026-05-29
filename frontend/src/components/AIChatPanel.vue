<template>
	<div class="flex flex-1 flex-col overflow-hidden bg-surface-white">
		<div
			class="flex shrink-0 items-center justify-between border-b border-outline-gray-1 bg-surface-white px-3 py-2.5"
		>
			<div class="text-[11px] leading-4 text-ink-gray-5">Session persists for this page</div>
			<button
				v-if="messages.length"
				class="text-xs text-ink-gray-4 hover:text-ink-gray-9"
				@click="clearSession"
			>
				Clear
			</button>
		</div>

		<div ref="messagesEl" class="no-scrollbar flex-1 space-y-4 overflow-y-auto px-4 py-4">
			<div
				v-if="!messages.length"
				class="flex h-full flex-col items-center justify-center gap-2 pb-8 text-center"
			>
				<FeatherIcon name="cpu" class="h-8 w-8 text-ink-gray-3" />
				<p class="text-xs text-ink-gray-4">Chat to create or edit page</p>
			</div>

			<template v-for="msg in messages" :key="msg.id">
				<div v-if="msg.role === 'user'" class="flex flex-col items-end">
					<div
						class="w-fit max-w-[88%] rounded-md border bg-surface-gray-1 px-3 py-2 text-sm text-ink-gray-8"
					>
						<div class="whitespace-pre-wrap break-words">{{ msg.content }}</div>
					</div>
				</div>
				<div v-else class="flex flex-col items-start">
					<div class="w-fit max-w-full text-sm text-ink-gray-8">
						<div class="whitespace-pre-wrap break-words">{{ msg.content }}</div>
					</div>
				</div>
			</template>

			<p v-if="loading" class="text-xs italic text-ink-gray-5">
				{{ statusMessage || "Generating…" }}
			</p>
		</div>

		<div class="shrink-0 border-t border-outline-gray-1 bg-surface-white p-4">
			<ErrorMessage v-if="error" :message="error" class="mb-2" />

			<div v-if="mode === 'modify'" class="mb-2 flex items-center gap-1.5 rounded py-1">
				<span class="truncate text-xs text-ink-gray-5">Editing:</span>
				<Badge variant="subtle" size="sm">
					{{ selectedBlock?.blockName || selectedBlock?.componentName }}
				</Badge>
			</div>

			<div class="relative">
				<textarea
					v-model="prompt"
					rows="4"
					class="w-full resize-none rounded border border-[--surface-gray-2] bg-surface-gray-2 px-2 py-1.5 text-sm text-ink-gray-8 placeholder-ink-gray-4 transition-colors hover:border-[--outline-gray-modals] hover:bg-surface-gray-3 focus:border-outline-gray-4 focus:bg-surface-white focus:shadow-sm focus:ring-0 focus-visible:ring-2 focus-visible:ring-outline-gray-3 disabled:cursor-not-allowed disabled:bg-surface-gray-1 disabled:text-ink-gray-5"
					:placeholder="promptPlaceholder"
					:disabled="loading"
					@keydown.meta.enter="generate"
					@keydown.ctrl.enter="generate"
				/>
			</div>

			<div class="mt-2 flex items-center justify-between gap-2">
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
						<div class="min-w-40 rounded-lg border border-outline-gray-2 bg-surface-white py-1 shadow-lg">
							<button
								v-for="option in modelOptions"
								:key="option.value"
								class="flex w-full items-center px-3 py-1.5 text-left text-sm text-ink-gray-7 hover:bg-surface-gray-2"
								:class="{ 'font-medium text-ink-gray-9': option.value === selectedModel }"
								@click="
									() => {
										selectedModel = option.value
										close()
									}
								"
							>
								{{ option.label }}
							</button>
						</div>
					</template>
				</Popover>

				<Button
					variant="solid"
					:label="mode === 'generate' ? 'Generate' : 'Edit'"
					icon="arrow-up"
					:loading="loading"
					:disabled="!prompt.trim()"
					@click="generate"
				/>
			</div>
		</div>
	</div>
</template>

<script lang="ts" setup>
import { ref, computed, inject, watch, nextTick } from "vue"
import { ErrorMessage, Button, Badge, FeatherIcon, call, createResource, Popover } from "frappe-ui"
import { toast } from "vue-sonner"
import useStudioStore from "@/stores/studioStore"
import useCanvasStore from "@/stores/canvasStore"
import { getBlockInstance, getBlockString } from "@/utils/serializer"
import { tryParseYamlBlock } from "@/utils/blockCodec"
import { useAIChatController, type AgentOperation } from "@/components/AIChatController"
import type Block from "@/utils/block"

const store = useStudioStore()
const canvasStore = useCanvasStore()
const socket = inject<any>("socket")
const { mode, selectedBlock, applyOperation } = useAIChatController()

const prompt = ref("")
const loading = ref(false)
const error = ref("")
const statusMessage = ref("")
const selectedModel = ref("")
const streamBuffer = ref("")
const modifyStreamBuffer = ref("")
const messages = ref<any[]>([])
const messagesEl = ref<HTMLElement | null>(null)

const pageId = computed(() => store.activePage?.name ?? "")

const promptPlaceholder = computed(() => {
	if (mode.value === "modify") return "Describe what to change in this block..."
	if (mode.value === "agent") return "Describe what to add or change on this page..."
	return "Ask to create a new page..."
})

const aiModels = createResource({
	url: "studio.ai.models.get_ai_models",
	auto: true,
	onSuccess(data: any[]) {
		if (data?.length && !selectedModel.value) {
			selectedModel.value = data[0].id
		}
	},
})

const modelOptions = computed(() => (aiModels.data ?? []).map((m: any) => ({ label: m.label, value: m.id })))

const modelLabel = computed(() => {
	const selected = modelOptions.value.find((m: any) => m.value === selectedModel.value)
	return selected ? selected.label : "Model"
})

const sessionResource = createResource({
	url: "studio.ai.page_generator.get_ai_session",
	onSuccess(data: any) {
		messages.value = data.messages ?? []
		if (data.selected_model && !selectedModel.value) {
			selectedModel.value = data.selected_model
		}
		scrollToBottom()
	},
})

function scrollToBottom() {
	nextTick(() => {
		if (messagesEl.value) {
			messagesEl.value.scrollTo({ top: messagesEl.value.scrollHeight, behavior: "smooth" })
		}
	})
}

function reloadSession() {
	if (pageId.value) {
		sessionResource.submit({ page_id: pageId.value })
	}
}

// — Generation handlers —
function onProgress(data: any) {
	statusMessage.value = data.message || "Generating…"
}

function onStream(data: any) {
	streamBuffer.value += data.chunk || ""
	const block = tryParseYamlBlock(streamBuffer.value)
	if (block) {
		const rootBlock = getBlockInstance(block)
		store.pageBlocks = [rootBlock]
		canvasStore.activeCanvas?.setRootBlock(rootBlock, false)
	}
}

async function onComplete(data: any) {
	loading.value = false
	statusMessage.value = ""
	streamBuffer.value = ""
	const block: Block = data.block
	if (!block) {
		error.value = "No block was generated. Try a more descriptive prompt."
		return
	}
	const rootBlock = getBlockInstance(block)
	store.pageBlocks = [rootBlock]
	canvasStore.activeCanvas?.setRootBlock(rootBlock, false)
	toast.success("Page generated successfully")
	prompt.value = ""
	reloadSession()
}

function onError(data: any) {
	loading.value = false
	statusMessage.value = ""
	streamBuffer.value = ""
	error.value = data.message || "Generation failed. Please check your Studio Settings and try again."
}

// — Modify handlers —
function onModifyProgress(data: any) {
	statusMessage.value = data.message || "Updating…"
}

function onModifyStream(data: any) {
	modifyStreamBuffer.value += data.chunk || ""
	const block = tryParseYamlBlock(modifyStreamBuffer.value)
	if (block) replaceBlockInTree(data.component_id, getBlockInstance(block))
}

async function onModifyComplete(data: any) {
	loading.value = false
	statusMessage.value = ""
	modifyStreamBuffer.value = ""
	const block: Block = data.block
	if (!block) {
		error.value = "No block was returned. Try a more specific request."
		return
	}
	replaceBlockInTree(data.component_id, getBlockInstance(block))
	toast.success("Block updated")
	prompt.value = ""
	reloadSession()
}

function onModifyError(data: any) {
	loading.value = false
	statusMessage.value = ""
	modifyStreamBuffer.value = ""
	error.value = data.message || "Update failed. Please try again."
}

// — Agent handlers —
function onAgentProgress(data: any) {
	statusMessage.value = data.message || "Thinking…"
}

function onAgentToolBatch(data: any) {
	const ops: AgentOperation[] = data.operations ?? []
	ops.forEach((op) => applyOperation(op))
}

function onAgentStream(data: any) {
	statusMessage.value = data.chunk || ""
}

async function onAgentComplete() {
	loading.value = false
	statusMessage.value = ""
	toast.success("Changes applied")
	prompt.value = ""
	reloadSession()
}

function onAgentError(data: any) {
	loading.value = false
	statusMessage.value = ""
	error.value = data.message || "Agent failed. Please try again."
}

// — Tree helpers —
function replaceBlockInTree(componentId: string, newBlock: Block) {
	const canvas = canvasStore.activeCanvas
	if (!canvas) return
	const oldBlock = canvas.findBlock(componentId)
	if (!oldBlock) return
	oldBlock.getParentBlock()?.replaceChild(oldBlock, newBlock)
}

function setupListeners() {
	if (!socket || !pageId.value) return
	const id = pageId.value
	socket.on(`ai_generation_progress_${id}`, onProgress)
	socket.on(`ai_generation_stream_${id}`, onStream)
	socket.on(`ai_generation_complete_${id}`, onComplete)
	socket.on(`ai_generation_error_${id}`, onError)
	socket.on(`ai_modify_progress_${id}`, onModifyProgress)
	socket.on(`ai_modify_stream_${id}`, onModifyStream)
	socket.on(`ai_modify_complete_${id}`, onModifyComplete)
	socket.on(`ai_modify_error_${id}`, onModifyError)
	socket.on(`ai_agent_progress_${id}`, onAgentProgress)
	socket.on(`ai_agent_tool_batch_${id}`, onAgentToolBatch)
	socket.on(`ai_agent_stream_${id}`, onAgentStream)
	socket.on(`ai_agent_complete_${id}`, onAgentComplete)
	socket.on(`ai_agent_error_${id}`, onAgentError)
}

function detachListeners() {
	if (!socket || !pageId.value) return
	const id = pageId.value
	socket.off(`ai_generation_progress_${id}`, onProgress)
	socket.off(`ai_generation_stream_${id}`, onStream)
	socket.off(`ai_generation_complete_${id}`, onComplete)
	socket.off(`ai_generation_error_${id}`, onError)
	socket.off(`ai_modify_progress_${id}`, onModifyProgress)
	socket.off(`ai_modify_stream_${id}`, onModifyStream)
	socket.off(`ai_modify_complete_${id}`, onModifyComplete)
	socket.off(`ai_modify_error_${id}`, onModifyError)
	socket.off(`ai_agent_progress_${id}`, onAgentProgress)
	socket.off(`ai_agent_tool_batch_${id}`, onAgentToolBatch)
	socket.off(`ai_agent_stream_${id}`, onAgentStream)
	socket.off(`ai_agent_complete_${id}`, onAgentComplete)
	socket.off(`ai_agent_error_${id}`, onAgentError)
}

watch(
	() => pageId.value,
	(newId, oldId) => {
		if (oldId) detachListeners()
		if (newId) {
			setupListeners()
			sessionResource.submit({ page_id: newId })
		}
	},
	{ immediate: true },
)

async function generate() {
	if (!prompt.value.trim()) return
	loading.value = true
	error.value = ""
	statusMessage.value = ""

	messages.value = [...messages.value, { id: Date.now(), role: "user", content: prompt.value }]
	scrollToBottom()

	try {
		if (mode.value === "modify" && selectedBlock.value) {
			await call("studio.ai.page_generator.modify_block_from_prompt", {
				prompt: prompt.value,
				block_context: getBlockString(selectedBlock.value),
				model: selectedModel.value,
				page_id: pageId.value,
				component_id: selectedBlock.value.componentId,
			})
		} else if (mode.value === "agent") {
			const rootBlock = canvasStore.activeCanvas?.getRootBlock()
			await call("studio.ai.agent.run_agent_from_prompt", {
				prompt: prompt.value,
				page_context: rootBlock ? getBlockString(rootBlock) : "{}",
				model: selectedModel.value,
				page_id: pageId.value,
			})
		} else {
			await call("studio.ai.page_generator.generate_page_from_prompt", {
				prompt: prompt.value,
				model: selectedModel.value,
				page_id: pageId.value,
			})
		}
	} catch (e: any) {
		loading.value = false
		statusMessage.value = ""
		error.value = e?.message || "Failed to start. Please try again."
	}
}

async function clearSession() {
	await call("studio.ai.page_generator.clear_ai_session", { page_id: pageId.value })
	messages.value = []
}
</script>
