<template>
	<AppComponent v-if="block" :block="block" />
</template>

<script setup lang="ts">
import { provide, computed } from "vue"
import AppComponent from "@/components/AppComponent.vue"
import Block from "@/utils/block"
import useComponentStore from "@/stores/componentStore"

import useCodeStore from "@/stores/codeStore"
import { isDynamicValue } from "@/utils/code"

const thisProps = defineProps<{
	studioComponent: Block
	evaluationContext: Object
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

const block = computed(() => componentStore.getNewStudioComponentInstance(thisProps.studioComponent))
</script>
