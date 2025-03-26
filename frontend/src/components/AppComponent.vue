<template>
	<component
		v-show="showComponent"
		:is="components.getComponent(block.componentName)"
		v-bind="componentProps"
		v-model="boundValue"
		:data-component-id="block.componentId"
		:style="styles"
		v-on="componentEvents"
	>
		<!-- Dynamically render named slots -->
		<template v-for="(slot, slotName) in block.componentSlots" :key="slotName" v-slot:[slotName]>
			<template v-if="Array.isArray(slot.slotContent)">
				<AppComponent v-for="slotBlock in slot.slotContent" :block="slotBlock" :key="slotBlock.componentId" />
			</template>
			<template v-else-if="isHTML(slot.slotContent)">
				<component :is="{ template: slot.slotContent }" />
			</template>
			<template v-else>
				{{ slot.slotContent }}
			</template>
		</template>
		<AppComponent v-for="child in block?.children" :key="child.componentId" :block="child" />
	</component>
</template>

<script>
import Block from "@/utils/block"
import { createResource } from "frappe-ui"
import components from "@/data/components"
import { getComponentRoot, isDynamicValue, getDynamicValue, isHTML, executeUserScript, getTemplateBinding } from "@/utils/helpers"
import { toast } from "vue-sonner"
import useAppStore from "@/stores/appStore"
import { toRefs } from "vue"
import { storeToRefs } from "pinia"

export default {
	name: 'AppComponent',
	setup() {
		const store = useAppStore()

		return {
			store
		}
	},
	props: {
		block: {
			type: Block,
			required: true
		}
	},
	data() {
		const { variables } = storeToRefs(this.store)
		return {
			componentRef: null,
			// Expose variables directly to template
			...toRefs(variables.value),
			components,
		}
	},
	computed: {
		styles() {
			return this.block.getStyles()
		},
		componentProps() {
			if (!this.block || this.block.isRoot()) return {}

			const propValues = { ...this.block.componentProps }

			Object.entries(propValues).forEach(([propName, config]) => {
				if (isDynamicValue(config)) {
					const binding = getTemplateBinding(config)
					if (binding.type === 'variable') {
						propValues[propName] = this.$data[binding.value]
					}
				}
			})

			console.log(propValues)

			return {
				...propValues,
				...this.$attrs
			}
		},
		showComponent() {
			if (this.block.visibilityCondition) {
				const value = getDynamicValue(this.block.visibilityCondition, {
					...this.store.resources,
					...this.store.variables
				})
				return typeof value === "string" ? value === "true" : value
			}
			return true
		},
		boundValue: {
			get() {
				const modelValue = this.block.componentProps.modelValue
				if (modelValue?.$type === "variable") {
					return this.store.variables[modelValue.name]
				} else if (isDynamicValue(modelValue)) {
					return getDynamicValue(modelValue, {
						...this.store.resources,
						...this.store.variables
					})
				}
				return modelValue
			},
			set(newValue) {
				const modelValue = this.block.componentProps.modelValue
				if (modelValue?.$type === "variable") {
					// Update the variable in the store
					this.store.variables[modelValue.name] = newValue
				} else {
					// Update the prop directly if not bound to a variable
					this.block.setProp("modelValue", newValue)
				}
			}
		},
		componentEvents() {
			const events = {}
			Object.entries(this.block.componentEvents).forEach(([eventName, event]) => {
				const getEventFn = () => {
					if (event.action === "Switch App Page") {
						return () => {
							this.$router.push({
								name: "AppContainer",
								params: {
									appRoute: this.$route.params.appRoute,
									pageRoute: this.getPageRoute(this.$route.params.appRoute, event.page)
								}
							})
						}
					} else if (event.action === "Call API") {
						return () => {
							const path = event.api_endpoint.split(".")
							// get resource
							const resource = this.store.resources[path[0]]

							if (resource) {
								// access and call whitelisted method
								resource[path[1]].submit()
							} else {
								createResource({
									url: event.api_endpoint,
									auto: true,
								})
							}
						}
					} else if (event.action === "Insert a Document") {
						return () => {
							const fields = {}
							event.fields.forEach((field) => {
								fields[field.field] = this.store.variables[field.value]
							})
							createResource({
								url: "frappe.client.insert",
								method: "POST",
								params: {
									doc: {
										doctype: event.doctype,
										...fields,
									},
								},
								onSuccess: () => {
									if (event.success_message) {
										toast.success(event.success_message)
									} else {
										toast.success(`${event.doctype} saved successfully`)
									}
								},
								onError: () => {
									if (event.error_message) {
										toast.error(event.error_message)
									} else {
										toast.error(`Error saving ${event.doctype}`)
									}
								},
							}).submit()
						}
					} else if (event.action === "Run Script") {
						return () => {
							executeUserScript(
								event.script,
								this.store.variables,
								this.store.resources
							)
						}
					}
				}
				events[eventName] = getEventFn()
			})

			return events
		}
	},
	methods: {
		getPageRoute(appRoute, page) {
			// extract page route from full page route
			return page.replace(`studio-app/${appRoute}/`, "")
		}
	},
}
</script>