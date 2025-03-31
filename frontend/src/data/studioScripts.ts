import { createListResource } from "frappe-ui"

const clientScriptResource = createListResource({
	doctype: "Studio Client Script",
	fields: ["script", "name"],
	pageLength: 500,
	auto: true,
})

const attachedScriptResource = createListResource({
	doctype: "Studio Page Client Script",
	parent: "Studio Page",
	fields: [
		"studio_script.script",
		"studio_script.name as script_name",
		"name",
	],
	orderBy: "`tabStudio Page Client Script`.creation asc",
})

export { clientScriptResource, attachedScriptResource }