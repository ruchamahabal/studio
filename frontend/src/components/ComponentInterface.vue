<template>
	<div class="flex select-none flex-col pb-16">
		<div class="flex flex-col gap-3">
			<!-- Props -->
			<SectionContainer title="Props">
				<template #actions>
					<Autocomplete
						:options="fieldTypeOptions"
						@update:modelValue="(option: SelectOption) => showAddPropPopover(option.value)"
						class="!w-auto"
					>
						<template #target="{ togglePopover }">
							<Button @click="togglePopover" size="sm" variant="ghost" icon="plus" />
						</template>
					</Autocomplete>
				</template>

				<div class="flex flex-col gap-1" v-if="componentProps.length > 0">
					<Popover
						v-for="(prop, index) in componentProps"
						:key="prop.prop"
						:show="showEditPopover && editingIndex === index"
						@update:show="
							(show: boolean) => {
								if (!show) cancelEdit()
							}
						"
						placement="bottom-center"
					>
						<template #target>
							<div
								class="group flex flex-1 cursor-pointer justify-between rounded border border-gray-300 px-2 py-1 hover:bg-gray-50"
								@click="editProp(prop, index)"
							>
								<div class="flex items-center gap-2">
									<FeatherIcon :name="getFieldTypeIcon(prop.type)" class="h-4 w-4 text-gray-500" />
									<span class="text-sm text-gray-800">{{ prop.prop }}</span>
								</div>
								<button
									class="flex cursor-pointer items-center rounded-sm p-1 text-gray-700 opacity-0 transition-opacity hover:text-gray-900 group-hover:opacity-100"
									@click.stop="componentEditorStore.removeComponentProp(index)"
								>
									<FeatherIcon name="x" class="h-4 w-4" />
								</button>
							</div>
						</template>
						<template #body-main>
							<div
								class="w-64 space-y-4 p-4"
								v-if="editingProp && editingIndex === index"
								@keydown="handleInputKeydown"
							>
								<FormControl
									type="text"
									label="Name"
									v-model="editingProp.prop"
									placeholder="e.g. user_name"
									autocomplete="off"
									:required="true"
								/>
								<FormControl
									type="autocomplete"
									label="Type"
									:options="fieldTypeOptions"
									:modelValue="
										editingProp ? fieldTypeOptions.find((opt) => opt.value === editingProp!.type) : null
									"
									@update:modelValue="
										(option: SelectOption) => {
											if (editingProp) {
												editingProp.type = option.value
												setPropControl()
											}
										}
									"
									:required="true"
								>
									<template #prefix>
										<FeatherIcon
											:name="editingProp ? getFieldTypeIcon(editingProp.type) : 'help-circle'"
											class="mr-1 h-3 w-3 text-gray-500"
										/>
									</template>
									<template #item-prefix="{ option }">
										<FeatherIcon :name="getFieldTypeIcon(option.value)" class="h-3 w-3 text-gray-500" />
									</template>
								</FormControl>
								<FormControl
									v-if="editingProp.type === 'select'"
									type="textarea"
									label="Options"
									v-model="editingProp.options"
									:required="true"
									placeholder="Enter list of options, each on a new line"
								/>

								<!-- Default value -->
								<component
									:is="editingProp.inputControl"
									:type="editingProp.inputType"
									label="Default Value"
									v-model="editingProp.default"
								/>
								<FormControl
									type="textarea"
									label="Description"
									v-model="editingProp.description"
									placeholder="Enter description (optional)"
								/>
								<FormControl
									type="checkbox"
									label="Is Required"
									size="sm"
									v-model="editingProp.required"
									class="[&>label]:text-sm [&>label]:text-ink-gray-5"
								/>
								<div class="flex gap-2">
									<Button variant="solid" @click="saveProp">Save</Button>
									<Button variant="outline" @click="cancelEdit">Cancel</Button>
								</div>
								<div class="text-xs text-gray-500">
									Press
									<kbd class="rounded bg-gray-100 px-1 py-0.5">⌘</kbd>
									+
									<kbd class="rounded bg-gray-100 px-1 py-0.5">S</kbd>
									to save
								</div>
							</div>
						</template>
					</Popover>
				</div>

				<EmptyState v-else message="No props added" />
			</SectionContainer>

			<!-- Test Props -->
			<SectionContainer title="Test Props">
				<PropsEditor
					v-if="componentEditorStore.studioComponentBlock"
					:block="componentEditorStore.studioComponentBlock"
					:isTestingComponent="true"
				/>
			</SectionContainer>
		</div>
	</div>
</template>

<script setup lang="ts">
import { ref, markRaw, computed } from "vue"
import { Autocomplete, Popover, FormControl } from "frappe-ui"
import EmptyState from "@/components/EmptyState.vue"
import type { SelectOption } from "@/types"
import type { ComponentPropUI } from "@/types/Studio/StudioComponent"
import Code from "@/components/Code.vue"
import ColorPicker from "@/components/ColorPicker.vue"
import PropsEditor from "@/components/PropsEditor.vue"
import useComponentEditorStore from "@/stores/componentEditorStore"
import { isCtrlOrCmd } from "@/utils/helpers"

const componentEditorStore = useComponentEditorStore()
const componentProps = computed(() => componentEditorStore.componentProps)
const showEditPopover = ref(false)
const editingProp = ref<ComponentPropUI | null>(null)
const editingIndex = ref<number>(-1)

const fieldTypeOptions = [
	{ label: "Text", value: "text" },
	{ label: "Number", value: "number" },
	{ label: "Checkbox", value: "checkbox" },
	{ label: "Textarea", value: "textarea" },
	{ label: "Select", value: "select" },
	{ label: "Code", value: "code" },
	{ label: "Color", value: "color" },
]

const getFieldTypeIcon = (type: string) => {
	const iconMap: Record<string, string> = {
		text: "type",
		number: "hash",
		checkbox: "check-square",
		textarea: "align-left",
		select: "list",
		code: "code",
		color: "droplet",
	}
	return iconMap[type] || "type"
}

const editProp = (input: ComponentPropUI, index: number) => {
	editingProp.value = { ...input }
	editingIndex.value = index
	setPropControl()
	showEditPopover.value = true
}

const saveProp = () => {
	if (editingProp.value && editingIndex.value >= 0) {
		componentEditorStore.updateComponentProp(editingIndex.value, editingProp.value)
	}
	showEditPopover.value = false
	editingProp.value = null
	editingIndex.value = -1
}

const cancelEdit = () => {
	showEditPopover.value = false
	editingProp.value = null
	editingIndex.value = -1
}

const showAddPropPopover = (fieldType: string) => {
	const fieldTypeLabel = fieldTypeOptions.find((opt) => opt.value === fieldType)?.label || fieldType
	const newPropData: ComponentPropUI = {
		prop: fieldTypeLabel,
		type: fieldType,
		description: "",
		default: "",
	}
	componentEditorStore.addComponentProp(newPropData)
	const newIndex = componentProps.value.length - 1
	setTimeout(() => {
		editProp(newPropData, newIndex)
	}, 10) // Small delay to ensure DOM is updated
}

const setPropControl = () => {
	if (!editingProp.value) return
	if (editingProp.value.type === "code") {
		editingProp.value.inputControl = markRaw(Code)
	} else if (editingProp.value.type === "color") {
		editingProp.value.inputControl = markRaw(ColorPicker)
	} else {
		editingProp.value.inputControl = "FormControl"
		editingProp.value.inputType = editingProp.value?.type === "textarea" ? "textarea" : "text"
	}
}

const handleInputKeydown = (e: KeyboardEvent) => {
	if (isCtrlOrCmd(e) && e.key === "s") {
		e.preventDefault()
		saveProp()
	}
}
</script>
