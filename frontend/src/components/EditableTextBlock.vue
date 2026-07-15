<template>
	<component :is="tag" :class="[fontSize, 'transition-colors']">
		<TextSelectionToolbar v-if="editor" :editor="editor" />
		<editor-content
			v-if="editor"
			:editor="editor"
			class="__text_editor__ outline-none"
			@keydown.esc.prevent="emit('stop')"
		/>
	</component>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, shallowRef } from "vue"
import { Editor, EditorContent, Extension } from "@tiptap/vue-3"
import { StarterKit } from "@tiptap/starter-kit"
import { TextStyle } from "@tiptap/extension-text-style"
import { Color } from "@tiptap/extension-color"
import { Underline } from "@tiptap/extension-underline"
import TextSelectionToolbar from "@/components/TextSelectionToolbar.vue"
import type { TextBlockProps } from "@/types/studio_components/TextBlock"

declare module "@tiptap/core" {
	interface Commands<ReturnType> {
		fontWeight: {
			setFontWeight: (weight: string) => ReturnType
			unsetFontWeight: () => ReturnType
		}
	}
}

const props = withDefaults(defineProps<TextBlockProps>(), {
	tag: "span",
	text: "Text Block",
	fontSize: "text-base",
})

const emit = defineEmits<{
	"update:text": [value: string]
	stop: []
}>()

// carry font-weight (espresso values) as an inline style on the textStyle mark so
// selection-scoped weight round-trips through the saved HTML, same as Color does for color
const FontWeight = Extension.create({
	name: "fontWeight",
	addGlobalAttributes() {
		return [
			{
				types: ["textStyle"],
				attributes: {
					fontWeight: {
						default: null,
						parseHTML: (element) => element.style.fontWeight || null,
						renderHTML: (attributes) =>
							attributes.fontWeight ? { style: `font-weight: ${attributes.fontWeight}` } : {},
					},
				},
			},
		]
	},
	addCommands() {
		return {
			setFontWeight:
				(weight: string) =>
				({ chain }) =>
					chain().setMark("textStyle", { fontWeight: weight }).run(),
			unsetFontWeight:
				() =>
				({ chain }) =>
					chain().setMark("textStyle", { fontWeight: null }).removeEmptyTextStyle().run(),
		}
	},
})

const editor = shallowRef<Editor>()

onMounted(() => {
	editor.value = new Editor({
		content: props.text,
		extensions: [
			StarterKit.configure({ link: { openOnClick: false }, underline: false, trailingNode: false }),
			TextStyle,
			Color.configure({ types: ["textStyle"] }),
			Underline,
			FontWeight,
		],
		autofocus: "all",
		injectCSS: false,
		onUpdate: ({ editor }) => emit("update:text", getInnerHTML(editor as Editor)),
	})
})

// a lone attribute-less <p> wrapper is redundant inside the block's own tag
const getInnerHTML = (ed: Editor) => {
	if (ed.isEmpty) return ""
	const html = ed.getHTML()
	const wrapped = html.match(/^<p>([\s\S]*)<\/p>$/)
	const doc = ed.state.doc
	if (doc.childCount === 1 && doc.firstChild?.type.name === "paragraph" && wrapped) {
		return wrapped[1]
	}
	return html
}

onBeforeUnmount(() => editor.value?.destroy())
</script>

<style scoped>
.__text_editor__ :deep(.ProseMirror) {
	outline: none;
	white-space: pre-wrap;
	/* blocks inherit select-none; re-enable native selection while editing */
	user-select: text;
	-webkit-user-select: text;
	caret-color: currentcolor;
}
.__text_editor__ :deep(.ProseMirror p) {
	margin: 0;
}
</style>
