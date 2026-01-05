<template>
	<component ref="component" v-if="compiledTemplate" :is="compiledTemplate"></component>
	<div ref="component" v-else v-html="props.html" v-bind="attrs"></div>
</template>
<script setup lang="ts">
import { computed, ref, compile, useAttrs, mergeProps } from "vue"
import type { HTMLProps } from "@/types/studio_components/HTML"

const component = ref<HTMLElement | null>(null)
const props = defineProps<HTMLProps>()
const attrs = useAttrs()
defineOptions({
	inheritAttrs: false,
})

const compiledTemplate = computed(() => {
	if (!props.html) return null
	try {
		const compileFn = compile(props.html, { hoistStatic: true })
		return (componentProps: any, ctx: any) => {
			// @ts-ignore
			const vnode = compileFn!(componentProps, ctx)
			if (vnode && typeof vnode === "object" && !Array.isArray(vnode)) {
				vnode.props = mergeProps(vnode.props || {}, attrs)
			}
			return vnode
		}
	} catch (e) {
		console.log("Error compiling template:", e)
		return null
	}
})

defineExpose({
	component,
})
</script>
