<template>
	<bubble-menu
		:editor="editor"
		:append-to="body"
		:options="{ strategy: 'fixed', placement: 'top' }"
		plugin-key="textSelectionToolbar"
		class="text-selection-toolbar z-50 flex items-center gap-0.5 rounded-md border border-outline-gray-2 bg-surface-base p-1 shadow-lg"
	>
		<button
			v-for="mark in inlineMarks"
			:key="mark.name"
			:title="mark.label"
			@mousedown.prevent="mark.toggle()"
			:class="[
				'flex rounded p-1 text-ink-gray-7 hover:bg-surface-gray-2',
				editor.isActive(mark.name) ? 'bg-surface-gray-3 text-ink-gray-9' : '',
			]"
		>
			<component :is="mark.icon" class="size-4" />
		</button>

		<div class="bg-outline-gray-2 mx-1 h-4 w-px" />

		<select
			:value="currentWeight"
			@change="setWeight(($event.target as HTMLSelectElement).value)"
			title="Font weight"
			class="h-6 cursor-pointer rounded border-none bg-transparent py-0 pl-1 pr-5 text-xs text-ink-gray-8 hover:bg-surface-gray-2 focus:outline-none"
		>
			<option value="">Weight</option>
			<option v-for="weight in weightOptions" :key="weight?.value" :value="weight?.value">
				{{ weight?.label }}
			</option>
		</select>

		<ColorPicker property="textColor" :modelValue="currentColor" @update:modelValue="setColor">
			<template #target="{ togglePopover }">
				<button
					title="Text color"
					class="flex rounded p-1 hover:bg-surface-gray-2"
					@mousedown.prevent="togglePopover()"
				>
					<span
						class="size-4 rounded border border-outline-gray-2"
						:style="{ background: currentColor || 'var(--ink-gray-8)' }"
					/>
				</button>
			</template>
		</ColorPicker>
	</bubble-menu>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { BubbleMenu } from "@tiptap/vue-3/menus"
import type { Editor } from "@tiptap/vue-3"
import LucideBold from "~icons/lucide/bold"
import LucideItalic from "~icons/lucide/italic"
import LucideUnderline from "~icons/lucide/underline"
import LucideStrikethrough from "~icons/lucide/strikethrough"
import ColorPicker from "@/components/ColorPicker.vue"
import { getEspressoTokens } from "@/utils/espressoTokens"

const props = defineProps<{
	editor: Editor
}>()

// append to body with a fixed strategy so the menu positions from the selection's real
// viewport rect, clearing the scaled/transformed canvas and its stacking context
const body = document.body

const inlineMarks = [
	{
		name: "bold",
		label: "Bold",
		icon: LucideBold,
		toggle: () => props.editor.chain().focus().toggleBold().run(),
	},
	{
		name: "italic",
		label: "Italic",
		icon: LucideItalic,
		toggle: () => props.editor.chain().focus().toggleItalic().run(),
	},
	{
		name: "underline",
		label: "Underline",
		icon: LucideUnderline,
		toggle: () => props.editor.chain().focus().toggleUnderline().run(),
	},
	{
		name: "strike",
		label: "Strikethrough",
		icon: LucideStrikethrough,
		toggle: () => props.editor.chain().focus().toggleStrike().run(),
	},
]

const weightOptions = getEspressoTokens("fontWeight").filter(
	(option): option is { label: string; value: string } => Boolean(option),
)

const currentWeight = computed(() => props.editor.getAttributes("textStyle").fontWeight || "")
const currentColor = computed(() => props.editor.getAttributes("textStyle").color || null)

function setWeight(weight: string) {
	if (weight) {
		props.editor.chain().focus().setFontWeight(weight).run()
	} else {
		props.editor.chain().focus().unsetFontWeight().run()
	}
}

function setColor(color: string | null) {
	if (color) {
		props.editor.chain().focus().setColor(color).run()
	} else {
		props.editor.chain().focus().unsetColor().run()
	}
}
</script>
