// Distill frappe-ui's auto-generated per-component API files
// (frappe-ui/src/components/<Name>/<Name>.api.md, written by its
// scripts/propsgen.ts) into ONE committed JSON the Studio AI serves at runtime
// (studio/ai/component_api.json). Run via `yarn sync-component-api` — chained
// into upgrade-frappeui-submodule so the JSON refreshes with the library.
//
// Only API facts survive the distillation (props/slots/emits) — none of the
// docs' Vue/Tailwind prose, which doesn't translate to Studio blocks.

import { readdirSync, readFileSync, writeFileSync, existsSync } from "node:fs"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const repo = join(dirname(fileURLToPath(import.meta.url)), "..", "..")
const componentsDir = join(repo, "frappe-ui", "src", "components")
const outFile = join(repo, "studio", "ai", "component_api.json")

if (!existsSync(componentsDir)) {
	console.error("frappe-ui submodule not initialized — nothing to distill")
	process.exit(1)
}

// Two propsgen formats: single-component files declare propsData/slotsData/
// emitsData (owner = the directory); family files (Sidebar, Settings, Tooltip)
// declare <camelCaseComponent>Props/Slots/Emits per sub-component.
const leanRows = (rows) =>
	rows.map(({ name, type, default: def, required, description }) => ({
		name,
		...(type ? { type } : {}),
		...(def && def !== "undefined" ? { default: def } : {}),
		...(required ? { required: true } : {}),
		...(description ? { description } : {}),
	}))

const extractAll = (source, dirComponent) => {
	const found = {}
	for (const match of source.matchAll(/const (\w+) = (\[[\s\S]*?\])\n/g)) {
		const [, variable, literal] = match
		let component, kind
		if (["propsData", "slotsData", "emitsData"].includes(variable)) {
			component = dirComponent
			kind = variable.replace("Data", "")
		} else {
			const parts = variable.match(/^(\w+?)(Props|Slots|Emits)$/)
			if (!parts) continue
			component = parts[1][0].toUpperCase() + parts[1].slice(1)
			kind = parts[2].toLowerCase()
		}
		// propsgen output is a JS literal (single quotes, unquoted keys) — evaluate it.
		const rows = leanRows(new Function(`return ${literal}`)())
		if (rows.length) (found[component] ??= {})[kind] = rows
	}
	return found
}

const api = {}
for (const entry of readdirSync(componentsDir).sort()) {
	const file = join(componentsDir, entry, `${entry}.api.md`)
	if (!existsSync(file)) continue
	for (const [component, data] of Object.entries(extractAll(readFileSync(file, "utf-8"), entry))) {
		api[component] = data
	}
}
// Molecules (the List family) keep their api.md beside the source, lowercase-named.
const moleculesDir = join(repo, "frappe-ui", "src", "molecules")
if (existsSync(moleculesDir)) {
	for (const entry of readdirSync(moleculesDir).sort()) {
		const dir = join(moleculesDir, entry)
		for (const name of existsSync(dir) ? readdirSync(dir) : []) {
			if (!name.endsWith(".api.md")) continue
			const owner = entry[0].toUpperCase() + entry.slice(1)
			for (const [component, data] of Object.entries(
				extractAll(readFileSync(join(dir, name), "utf-8"), owner),
			)) {
				api[component] = data
			}
		}
	}
}

const sorted = Object.fromEntries(Object.entries(api).sort(([a], [b]) => a.localeCompare(b)))
writeFileSync(outFile, JSON.stringify(sorted, null, "\t") + "\n")
console.log(`component_api.json: ${Object.keys(api).length} components`)

// --- Family scaffolds -------------------------------------------------------
// The editor's canonical compositions (familyTemplates.ts — what dropping List /
// SettingsDialog / Sidebar onto the canvas inserts). Distilled to the AI's
// compact block schema so describe_component and the prompts teach the SAME
// structure the editor builds — one source of truth for "how is this composed".

const esbuild = await import(join(repo, "frontend", "node_modules", "esbuild", "lib", "main.js"))
const templatesSource = readFileSync(
	join(repo, "frontend", "src", "utils", "blockTemplate", "familyTemplates.ts"),
	"utf-8",
)
// Type-only imports erase; nothing else in the module reaches outside the file.
const js = esbuild.transformSync(templatesSource.replace(/^import type .*$/gm, ""), {
	loader: "ts",
	format: "esm",
}).code
const module_ = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"))

const compact = (block) => {
	const out = {}
	if (block.componentName) out.name = block.componentName
	if (block.originalElement) out.originalElement = block.originalElement
	if (block.blockName) out.label = block.blockName
	if (block.componentProps && Object.keys(block.componentProps).length) out.props = block.componentProps
	if (block.baseStyles && Object.keys(block.baseStyles).length) out.style = block.baseStyles
	if (block.classes?.length) out.classes = block.classes
	if (block.children?.length) out.c = block.children.map(compact)
	if (block.componentSlots) {
		const slots = {}
		for (const [slotName, slot] of Object.entries(block.componentSlots)) {
			slots[slotName] = (slot.slotContent ?? []).map(compact)
		}
		if (Object.keys(slots).length) out.slots = slots
	}
	return out
}

const scaffolds = {}
for (const [family, template] of Object.entries(module_.familyTemplates)) {
	scaffolds[family] = compact(template())
}
const scaffoldFile = join(repo, "studio", "ai", "family_templates.json")
writeFileSync(scaffoldFile, JSON.stringify(scaffolds, null, "\t") + "\n")
console.log(`family_templates.json: ${Object.keys(scaffolds).join(", ")}`)
