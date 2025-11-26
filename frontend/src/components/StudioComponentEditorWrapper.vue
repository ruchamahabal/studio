<template>
	<StudioComponent v-if="studioComponent" :block="studioComponent" :breakpoint="thisProps.breakpoint" />
</template>

<script setup lang="ts">
import { provide, computed } from "vue"
import StudioComponent from "@/components/StudioComponent.vue"
import Block from "@/utils/block"
import useComponentEditorStore from "@/stores/componentEditorStore"

const thisProps = defineProps<{
	studioComponent: Block
	breakpoint?: string
}>()

const componentEditorStore = useComponentEditorStore()
const componentBlock = computed(() => componentEditorStore.studioComponentBlock!)

const componentContext = computed(() => {
	const context = componentBlock.value.getPropsAndAttributes()
	componentEditorStore.componentProps.forEach((item) => {
		if (!(item.prop in context) && item.default !== undefined) {
			context[item.prop] = item.default
		}
	})
	return { props: context }
})

provide("componentContext", componentContext)
</script>
