<template>
	<div v-if="visibleSteps.length" class="flex w-full flex-col gap-1">
		<div
			v-for="step in visibleSteps"
			:key="step.id"
			class="flex items-start gap-1.5 text-[11px] leading-4 text-ink-gray-5"
		>
			<template v-if="step.kind === 'tool'">
				<FeatherIcon
					v-if="step.status === 'running'"
					name="loader"
					class="mt-0.5 h-3 w-3 shrink-0 animate-spin text-ink-gray-4"
				/>
				<FeatherIcon v-else name="check" class="mt-0.5 h-3 w-3 shrink-0 text-ink-green-3" />
				<span class="break-words">
					{{ step.summary || step.tool }}
					<span v-if="step.ms" class="text-ink-gray-4">· {{ formatMs(step.ms) }}</span>
				</span>
			</template>
			<template v-else-if="step.kind === 'thinking'">
				<FeatherIcon name="wind" class="mt-0.5 h-3 w-3 shrink-0 text-ink-gray-4" />
				<details class="min-w-0 flex-1">
					<summary class="cursor-pointer select-none text-ink-gray-4">Thought for a moment</summary>
					<p class="mt-1 whitespace-pre-wrap break-words italic text-ink-gray-4">{{ step.text }}</p>
				</details>
			</template>
			<template v-else>
				<FeatherIcon name="message-circle" class="mt-0.5 h-3 w-3 shrink-0 text-ink-gray-4" />
				<span class="break-words text-ink-gray-6">{{ step.text }}</span>
			</template>
		</div>
	</div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { FeatherIcon } from "frappe-ui"

const props = defineProps<{ steps: any[] }>()

const visibleSteps = computed(() =>
	(props.steps || []).filter(
		(s) => s.kind === "tool" || (s.kind === "text" && s.text) || (s.kind === "thinking" && s.text),
	),
)

function formatMs(ms: number): string {
	return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}
</script>
