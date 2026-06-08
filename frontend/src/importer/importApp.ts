// Orchestrates importing a set of CRM pages into a Studio manifest.

import { join } from "node:path"

import { parseVueFile } from "./sfc"
import { analyzeScript } from "./script"
import { mapTemplateChildren, type MapContext } from "./template"
import { buildRootBlock, copyCustomComponents, type CopyConfig } from "./emit"
import type { Manifest, ManifestPage, ImportNote } from "./types"

export interface PageSpec {
	page_title: string
	route: string
	file: string // path relative to crmSrc, e.g. "pages/Contacts.vue"
}

export interface ImportConfig {
	app_name: string
	app_title: string
	frappe_app: string
	crmSrc: string // absolute path to crm/frontend/src
	appPath: string // absolute path to crm app root
	pages: PageSpec[]
}

export function importApp(config: ImportConfig): Manifest {
	const report: ImportNote[] = []
	const customComponents = new Map<string, string>()
	const pages: ManifestPage[] = []

	for (const spec of config.pages) {
		pages.push(importPage(spec, config, customComponents, report))
	}

	const copyConfig: CopyConfig = {
		crmSrc: config.crmSrc,
		appPath: config.appPath,
		studioApp: config.app_name,
	}
	const custom_components = copyCustomComponents(customComponents, copyConfig, report)

	return {
		app_name: config.app_name,
		app_title: config.app_title,
		frappe_app: config.frappe_app,
		pages,
		custom_components,
		report,
	}
}

function importPage(
	spec: PageSpec,
	config: ImportConfig,
	customComponents: Map<string, string>,
	report: ImportNote[],
): ManifestPage {
	const parsed = parseVueFile(join(config.crmSrc, spec.file))
	const analysis = analyzeScript(parsed.scriptContent)

	const ctx: MapContext = {
		pageName: spec.page_title,
		imports: parsed.imports,
		customComponents,
		report,
	}
	const topBlocks = mapTemplateChildren(parsed.templateAst, ctx)
	const root = buildRootBlock(topBlocks)

	for (const call of analysis.storeCalls) {
		report.push({
			page: spec.page_title,
			kind: "store-dropped",
			detail: `store/composable call "${call}" not imported (Studio has no app-level stores; keep state in-component)`,
		})
	}

	return {
		page_title: spec.page_title,
		route: spec.route,
		blocks: [root],
		resources: analysis.resources,
		variables: analysis.variables,
		watchers: analysis.watchers,
		client_scripts: analysis.clientScripts,
	}
}
