import { defineStore } from "pinia"
import { ref } from "vue"
import { studioComponents } from "@/data/studioComponents"
import { getBlockObject, getBlockInstance, confirm, getComponentBlock } from "@/utils/helpers"
import getBlockTemplate from "@/utils/blockTemplate"
import Block from "@/utils/block"
import useCanvasStore from "@/stores/canvasStore"
import { toast } from "vue-sonner"
import type { StudioComponent, ComponentPropUI } from "@/types/Studio/StudioComponent"
import useComponentStore from "@/stores/componentStore"
import useStudioStore from "./studioStore"

const useComponentEditorStore = defineStore("componentEditorStore", () => {
	const selectedComponent = ref<string | null>(null)
	const studioComponentBlock = ref<Block | null>(null)
	const componentProps = ref<ComponentPropUI[]>([])
	const componentStore = useComponentStore()

	async function createComponent(componentName: string, block?: Block | null) {
		const component: any = { component_name: componentName }
		if (block) {
			component.block = getBlockObject(block)
			if (component.block?.parentSlotName) {
				// remove parentSlotName from the top-level block of the component
				delete component.block.parentSlotName
			}
		}

		return studioComponents.insert.submit(component, {
			onSuccess(data: any) {
				componentStore.cacheComponent(data)
				toast.success("Component created successfully")
				return data
			},
			onError(error: any) {
				toast.error("Failed to create component", {
					description: error?.messages?.join(", "),
				})
			},
		})
	}

	function saveComponent(block: Block, componentName: string) {
		const payload: any = {
			name: componentName,
			block: getBlockObject(block),
		}

		payload.props = componentProps.value.map((item) => ({
			prop: item.prop,
			type: item.type,
			description: item.description || "",
			default: item.default || "",
			required: 0,
			options: item.options,
		}))

		studioComponents.setValue.submit(payload, {
			onSuccess(data: StudioComponent) {
				componentStore.cacheComponent(data)
				resetStudioComponent()
				toast.success("Component saved successfully")
			},
			onError(error: any) {
				toast.error("Failed to save component", {
					description: error.messages.join(", "),
				})
			},
		})
	}

	async function editComponent(componentId: string) {
		const componentDoc = componentStore.getComponentDoc(componentId)
		const componentBlock = await componentStore.getComponent(componentId)
		const block = componentBlock || getBlockInstance(getBlockTemplate("empty-component"))
		studioComponentBlock.value = getComponentBlock(componentId, true)

		// Load existing props from the component doc
		if (componentDoc && componentDoc.props) {
			componentProps.value = componentDoc.props.map((item: any) => ({
				prop: item.prop,
				type: item.type,
				description: item.description,
				default: item.default,
				options: item.options,
			}))
		} else {
			componentProps.value = []
		}

		const canvasStore = useCanvasStore()
		canvasStore.editOnCanvas(
			block,
			(editedBlock) => saveComponent(editedBlock, componentDoc.component_id),
			"Save Component",
			componentDoc.component_name,
			componentDoc.component_id,
			"component",
			() => resetStudioComponent(),
		)
	}

	async function deleteComponent(component: StudioComponent) {
		if (isComponentUsed(component.component_id)) {
			toast.error("Component is used in this page. You cannot delete it.")
		} else {
			const confirmed = await confirm(
				`Are you sure you want to delete the component '${component.component_name}'?`,
			)
			if (confirmed) {
				const store = useStudioStore()
				studioComponents.runDocMethod
					.submit({
						method: "delete_component",
						name: component.component_id,
						studio_app: store.activeApp?.name,
					})
					.then(() => {
						toast.success(`Component '${component.component_name}' deleted successfully`)
						studioComponents.reload()
						componentStore.removeCachedComponent(component.component_id)
					})
					.catch(() => {
						toast.error(`Failed to delete component '${component.component_name}'`)
					})
			}
		}
	}

	function isComponentUsed(componentId: string): Boolean {
		const checkComponent = (block: Block) => {
			if (block.isStudioComponent && block.componentName === componentId) {
				return true
			}
			if (block.children) {
				for (const child of block.children) {
					if (checkComponent(child)) {
						return true
					}
				}
			}
			return false
		}
		const canvasStore = useCanvasStore()
		for (const block of canvasStore.activeCanvas?.getRootBlock()?.children || []) {
			if (checkComponent(block)) {
				return true
			}
		}
		return false
	}

	function resetStudioComponent() {
		studioComponentBlock.value = null
	}

	// component props
	function addComponentProp(prop: ComponentPropUI) {
		componentProps.value.push(prop)
	}

	function updateComponentProp(index: number, prop: ComponentPropUI) {
		if (index >= 0 && index < componentProps.value.length) {
			componentProps.value[index] = prop
		}
	}

	function removeComponentProp(index: number) {
		if (index >= 0 && index < componentProps.value.length) {
			componentProps.value.splice(index, 1)
		}
	}

	function clearComponentProps() {
		componentProps.value = []
	}

	return {
		selectedComponent,
		studioComponentBlock,
		componentProps,
		createComponent,
		editComponent,
		deleteComponent,
		// props
		addComponentProp,
		updateComponentProp,
		removeComponentProp,
		clearComponentProps,
	}
})

export default useComponentEditorStore
