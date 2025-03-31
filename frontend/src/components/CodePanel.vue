<template>
	<div class="flex h-full w-48 flex-col justify-between gap-1">
		<div class="flex flex-col gap-1">
			<a
				v-for="script in attachedScriptResource.data"
				href="#"
				@click=""
				class="group flex h-6 items-center justify-between gap-1 text-sm font-medium text-ink-gray-8 last-of-type:mb-2"
			>
				<div class="flex w-[90%] items-center gap-1">
					<EditableSpan
						v-model="script.script_name"
						:editable="script.editable"
						:onChange="
							async (newName) => {
								await updateScriptName(newName, script)
							}
						"
						class="w-full truncate"
					>
						{{ script.script_name }}
					</EditableSpan>
				</div>
				<Dropdown
					class="script-options"
					placement="right"
					:options="[
						{
							label: 'Rename',
							onClick: () => {
								script.editable = true
							},
							icon: 'edit',
						},
						{
							label: 'Remove Script',
							onClick: () => deleteScript(script.name),
							icon: 'trash',
						},
					]"
				>
					<template v-slot="{ open }">
						<Button icon="more-horizontal" size="sm" variant="ghost" @click="open"></Button>
					</template>
				</Dropdown>
			</a>
		</div>
		<div class="text-xs leading-4 text-ink-gray-6">
			<b>Note:</b>
			All client scripts are executed on published pages.
		</div>
	</div>
</template>

<script setup lang="ts">
import { createListResource, createResource } from "frappe-ui"
import EditableSpan from "@/components/EditableSpan.vue"
import { StudioPage } from "@/types/Studio/StudioPage"

const props = defineProps<{
	page: StudioPage
}>()

type attachedScript = {
	script: string
	name: string
	script_name: string
}

const attachedScriptResource = createListResource({
	doctype: "Studio Page Client Script",
	parent: "Studio Page",
	filters: {
		parent: props.page.name,
	},
	fields: ["studio_script.script", "studio_script.name as script_name", "name"],
	orderBy: "`tabStudio Page Client Script`.creation asc",
	auto: true,
})

const clientScriptResource = createListResource({
	doctype: "Studio Client Script",
	fields: ["script", "name"],
	pageLength: 500,
	auto: true,
})

const deleteScript = (scriptName: string) => {
	attachedScriptResource.delete.submit(scriptName).then(() => {
		attachedScriptResource.reload()
	})
}

const updateScriptName = async (newName: string, script: attachedScript) => {
	if (!newName) return
	return createResource({
		url: "frappe.client.rename_doc",
	})
		.submit({
			doctype: "Studio Client Script",
			old_name: script?.script_name,
			new_name: newName,
		})
		.then(async () => {
			attachedScriptResource.data = attachedScriptResource.data.map(
				(s: { script_name: string; script: string }) => {
					if (s.script_name === script.script_name) {
						s.script_name = newName
					}
					return s
				},
			)
		})
}
</script>
