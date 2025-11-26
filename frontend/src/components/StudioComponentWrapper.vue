<template>
	<StudioComponent v-if="block" :block="block" :breakpoint="thisProps.breakpoint" />
</template>

<script setup lang="ts">
import { provide, computed } from "vue"
import StudioComponent from "@/components/StudioComponent.vue"
import Block from "@/utils/block"
import useComponentStore from "@/stores/componentStore"
import useCodeStore from "@/stores/codeStore"
import { isDynamicValue } from "@/utils/code"

const thisProps = defineProps<{
	studioComponent: Block
	evaluationContext: Object
	breakpoint?: string
}>()
const componentStore = useComponentStore()
const codeStore = useCodeStore()

const componentContext = computed(() => {
	const context = thisProps.studioComponent.getPropsAndAttributes()
	const componentDoc = componentStore.getComponentDoc(thisProps.studioComponent.componentName)
	if (componentDoc?.props) {
		componentDoc.props.forEach((item: any) => {
			if (!(item.prop in context) && item.default !== undefined) {
				context[item.prop] = item.default
			}

			Object.entries(context).forEach(([propName, value]) => {
				if (isDynamicValue(value)) {
					context[propName] = codeStore.getDynamicValue(value, thisProps.evaluationContext)
				}
			})
		})
	}
	return { props: context }
})
provide("componentContext", componentContext)

const block = computed(() => {
	const newBlock = componentStore.getNewStudioComponentInstance(thisProps.studioComponent)
	if (!newBlock) {
		console.error(`Component with ID ${thisProps.studioComponent.componentName} not found`)
		return
	}
	newBlock.initializeStudioComponent(thisProps.studioComponent)
	return newBlock
})
</script>
