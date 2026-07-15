<template>
	<!-- v-html so inline formatting (bold/color spans) applied in the editor renders here and in the shipped app -->
	<component :is="tag" :class="[fontSize, 'transition-colors']" v-html="text" />
</template>

<script setup lang="ts">
import type { TextBlockProps } from "@/types/studio_components/TextBlock"

withDefaults(defineProps<TextBlockProps>(), {
	tag: "span",
	text: "Text Block",
	fontSize: "text-base",
})
</script>
