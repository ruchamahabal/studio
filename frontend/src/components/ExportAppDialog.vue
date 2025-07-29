<template>
	<Dialog
		v-model="showDialog"
		:options="{
			title: `Export ${store.activeApp?.app_title} App`,
			size: 'xl',
		}"
		@after-leave="
			() => {
				targetApp = ''
			}
		"
	>
		<template #body-content>
			<div class="flex flex-col space-y-4">
				<div class="flex flex-col space-y-1.5">
					<span class="text-base font-medium leading-normal text-ink-gray-8">Frappe App</span>
					<FormControl
						:required="true"
						type="autocomplete"
						placeholder="Select the target Frappe App"
						:modelValue="targetApp"
						@update:modelValue="(v: SelectOption) => (targetApp = v.value || '')"
						:options="targetAppOptions"
					/>
				</div>
				<Switch
					v-if="store.activeApp?.is_standard"
					size="sm"
					label="Disable App Export"
					:modelValue="!store.activeApp?.is_standard"
					@update:modelValue="
						(value: boolean) => {
							if (value) {
								disableAppExport()
							}
						}
					"
				/>
			</div>
		</template>

		<template #actions>
			<Button variant="solid" label="Export" @click="exportApp" class="w-full" />
		</template>
	</Dialog>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { FormControl, Button, call, Switch } from "frappe-ui"
import type { SelectOption } from "@/types"
import { toast } from "vue-sonner"
import useStudioStore from "@/stores/studioStore"
import { studioApps } from "@/data/studioApps"

const showDialog = defineModel("showDialog", { type: Boolean, required: true })

const store = useStudioStore()
const targetApp = ref(store.activeApp?.frappe_app)
let targetAppOptions: string[] = []

call("frappe.core.doctype.module_def.module_def.get_installed_apps").then((data: string[]) => {
	if (typeof data === "string") {
		data = JSON.parse(data)
	}
	targetAppOptions = data || []
})

function exportApp() {
	return studioApps.runDocMethod.submit(
		{
			name: store.activeApp?.app_name,
			method: "enable_app_export",
			target_app: targetApp.value,
		},
		{
			onSuccess: () => {
				toast.success("App exported successfully")
				showDialog.value = false
			},
			onError: (error: any) => {
				toast.error("Failed to export app", {
					description: error?.messages?.join(", "),
					duration: Infinity,
				})
			},
		},
	)
}

function disableAppExport() {
	return studioApps.runDocMethod.submit(
		{
			name: store.activeApp?.app_name,
			method: "disable_app_export",
		},
		{
			onSuccess: () => {
				toast.success("App export disabled")
				showDialog.value = false
			},
			onError: (error: any) => {
				toast.error("Failed to disable app export", {
					description: error?.messages?.join(", "),
					duration: Infinity,
				})
			},
		},
	)
}
</script>
