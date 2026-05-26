<template>
	<div class="flex h-full flex-col overflow-hidden">
		<div ref="messagesEl" class="flex flex-1 flex-col gap-3 overflow-y-auto p-3 hide-scrollbar">
			<div
				v-if="!messages.length"
				class="flex h-full flex-col items-center justify-center gap-3 px-4 text-center"
			>
				<div class="flex h-10 w-10 items-center justify-center rounded-full bg-surface-gray-2">
					<FeatherIcon name="cpu" class="h-5 w-5 text-ink-gray-5" />
				</div>
				<div class="flex flex-col gap-1">
					<p class="text-sm font-medium text-ink-gray-7">AI Page Builder</p>
					<p class="text-xs leading-4 text-ink-gray-5">
						Describe the page you want and watch it appear on the canvas.
					</p>
				</div>
			</div>

			<template v-else>
				<div v-for="msg in messages" :key="msg.id" class="flex flex-col gap-1">
					<div v-if="msg.role === 'user'" class="flex justify-end">
						<div
							class="max-w-[85%] rounded-lg rounded-br-sm bg-surface-gray-2 px-3 py-2 text-xs text-ink-gray-8"
						>
							{{ msg.content }}
						</div>
					</div>

					<div v-else class="flex flex-col gap-1">
						<div class="flex items-center gap-1.5 text-xs font-medium text-ink-gray-5">
							<FeatherIcon name="cpu" class="h-3.5 w-3.5" />
							AI
						</div>
						<div class="rounded-lg rounded-tl-sm border border-outline-gray-2 bg-surface-white px-3 py-2">
							<p v-if="msg.error" class="text-xs text-red-600">{{ msg.content }}</p>
							<p v-else-if="msg.stopped" class="text-xs text-ink-gray-4">Stopped.</p>
							<div v-else class="flex flex-col gap-1">
								<div
									v-for="(block, i) in msg.blocks"
									:key="i"
									class="flex items-center gap-1.5 text-xs"
									:class="msg.done ? 'text-ink-gray-6' : 'text-ink-gray-5'"
								>
									<FeatherIcon
										:name="msg.done ? 'check' : 'loader'"
										class="h-3 w-3 flex-shrink-0"
										:class="{ 'animate-spin': !msg.done && i === msg.blocks.length - 1 }"
									/>
									<span class="truncate font-mono">{{ block }}</span>
								</div>
								<p
									v-if="!msg.done && !msg.blocks.length"
									class="flex items-center gap-1.5 text-xs text-ink-gray-4"
								>
									<FeatherIcon name="loader" class="h-3 w-3 animate-spin" />
									Generating...
								</p>
								<p v-if="msg.done" class="mt-1 text-xs text-ink-gray-4">
									{{ msg.blocks.length }} block{{ msg.blocks.length === 1 ? "" : "s" }} added
								</p>
							</div>
						</div>
					</div>
				</div>
			</template>
		</div>

		<div class="flex flex-col gap-2 border-t border-outline-gray-2 p-3">
			<OptionToggle :options="modes" v-model="mode" />
			<Textarea
				v-model="prompt"
				placeholder="Describe the page you want to build..."
				:rows="5"
				:disabled="isGenerating"
				@keydown.meta.enter.prevent="submit"
				@keydown.ctrl.enter.prevent="submit"
			/>
			<div class="flex gap-2">
				<Button
					v-if="isGenerating"
					label="Stop"
					variant="subtle"
					size="sm"
					icon-left="square"
					@click="stopGeneration"
					class="flex-1"
				/>
				<Button
					v-else
					label="Generate"
					variant="solid"
					size="sm"
					:disabled="!prompt.trim()"
					@click="submit"
					class="flex-1"
				/>
			</div>
		</div>
	</div>
</template>

<script setup lang="ts">
import { ref, reactive, nextTick, inject, onUnmounted } from "vue"
import { FeatherIcon, Button, Textarea, call } from "frappe-ui"

import Block from "@/utils/block"
import { getBlockInstance } from "@/utils/serializer"
import useStudioStore from "@/stores/studioStore"
import useCanvasStore from "@/stores/canvasStore"
import OptionToggle from "@/components/OptionToggle.vue"
import type { BlockOptions } from "@/types"

interface AIMessage {
	id: string
	role: "user" | "assistant"
	content: string
	blocks: string[]
	done: boolean
	error: boolean
	stopped: boolean
}

const store = useStudioStore()
const canvasStore = useCanvasStore()
const socket = inject<any>("socket")

const prompt = ref("")
const isGenerating = ref(false)
const messages = ref<AIMessage[]>([])
const messagesEl = ref<HTMLElement | null>(null)
const mode = ref<"replace" | "append">("replace")

const modes = [
	{ label: "Replace page", value: "replace" as const },
	{ label: "Add to page", value: "append" as const },
]

let activeHandlers: { event: string; fn: (...args: any[]) => void }[] = []
let activeMsg: AIMessage | null = null

function scrollToBottom() {
	nextTick(() => {
		if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
	})
}

function makeId() {
	return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function blockLabel(block: BlockOptions) {
	if (block.blockName && block.blockName !== "container" && block.blockName !== "body") {
		return block.blockName
	}
	return block.componentName || "block"
}

function applyFullPageBlocks(blocks: BlockOptions[], msg: AIMessage) {
	if (!blocks.length) return
	const rootData = blocks[0]
	const children = rootData.children || []
	if (mode.value === "replace") {
		const rootBlock = getBlockInstance(rootData, false)
		store.pageBlocks[0] = rootBlock
		canvasStore.activeCanvas?.setRootBlock(rootBlock)
		msg.blocks = children.map(blockLabel)
	} else {
		const root = store.pageBlocks[0]
		if (!root) return
		for (const child of children) {
			const childBlock = reactive(new Block(child)) as Block
			childBlock.parentBlock = root
			root.children.push(childBlock)
			msg.blocks.push(blockLabel(child))
		}
	}
}

function cleanupListeners() {
	if (!socket) return
	for (const { event, fn } of activeHandlers) socket.off(event, fn)
	activeHandlers = []
}

function finishGeneration(msg: AIMessage) {
	msg.done = true
	isGenerating.value = false
	activeMsg = null
	cleanupListeners()
	canvasStore.activeCanvas?.clearSelection()
	scrollToBottom()
}

function failGeneration(msg: AIMessage, message: string) {
	msg.content = message
	msg.error = true
	msg.done = true
	isGenerating.value = false
	activeMsg = null
	cleanupListeners()
	scrollToBottom()
}

function stopGeneration() {
	if (!activeMsg) return
	activeMsg.stopped = true
	activeMsg.done = true
	isGenerating.value = false
	activeMsg = null
	cleanupListeners()
	canvasStore.activeCanvas?.clearSelection()
	scrollToBottom()
}

function subscribeToStreamEvents(jobId: string, msg: AIMessage) {
	const blockMap = new Map<string, Block>()

	const onBlock = (data: any) => {
		if (data.job_id !== jobId) return
		const { block, temp_id, parent_temp_id, is_root } = data

		if (is_root) {
			if (mode.value === "replace") {
				const rootBlock = getBlockInstance({ ...block, children: [] }, false)
				store.pageBlocks[0] = rootBlock
				canvasStore.activeCanvas?.setRootBlock(rootBlock)
				blockMap.set(temp_id, rootBlock)
			} else {
				const existing = store.pageBlocks[0]
				if (existing) blockMap.set(temp_id, existing)
			}
		} else {
			const parent = (parent_temp_id && blockMap.get(parent_temp_id)) || store.pageBlocks[0]
			if (!parent) return
			const childBlock = reactive(new Block(block)) as Block
			childBlock.parentBlock = parent
			parent.children.push(childBlock)
			blockMap.set(temp_id, childBlock)
			msg.blocks.push(blockLabel(block))
		}
		scrollToBottom()
	}
	const onComplete = (data: any) => {
		if (data.job_id === jobId) finishGeneration(msg)
	}
	const onError = (data: any) => {
		if (data.job_id === jobId) failGeneration(msg, data.message || "Something went wrong.")
	}

	socket.on("studio_ai_block", onBlock)
	socket.on("studio_ai_complete", onComplete)
	socket.on("studio_ai_error", onError)
	activeHandlers = [
		{ event: "studio_ai_block", fn: onBlock },
		{ event: "studio_ai_complete", fn: onComplete },
		{ event: "studio_ai_error", fn: onError },
	]
}

async function submit() {
	const text = prompt.value.trim()
	if (!text || isGenerating.value) return

	messages.value.push({
		id: makeId(),
		role: "user",
		content: text,
		blocks: [],
		done: false,
		error: false,
		stopped: false,
	})
	prompt.value = ""
	isGenerating.value = true
	scrollToBottom()

	const msg: AIMessage = {
		id: makeId(),
		role: "assistant",
		content: "",
		blocks: [],
		done: false,
		error: false,
		stopped: false,
	}
	messages.value.push(msg)
	activeMsg = msg

	const jobId = makeId()

	if (socket) {
		subscribeToStreamEvents(jobId, msg)
		try {
			await call("studio.studio.ai.generate_page_streaming", { prompt: text, job_id: jobId })
		} catch (e: any) {
			failGeneration(msg, e?.message || "Failed to start generation.")
		}
	} else {
		try {
			const result = await call("studio.studio.ai.generate_page_from_prompt", { prompt: text })
			const blocks: BlockOptions[] = typeof result === "string" ? JSON.parse(result) : result
			if (blocks?.length) applyFullPageBlocks(blocks, msg)
			finishGeneration(msg)
		} catch (e: any) {
			failGeneration(msg, e?.message || "Generation failed.")
		}
	}
}

onUnmounted(cleanupListeners)
</script>
