// Builds the page root block and copies wrapped composite SFCs into the target
// frappe app's studio folder so Studio's custom-component discovery finds them.

import { existsSync, mkdirSync, copyFileSync } from "node:fs"
import { join, dirname, basename } from "node:path"

import type { ManifestBlock, CustomComponentRecord, ImportNote } from "./types"

const BODY_STYLES = {
	alignItems: "flex-start",
	display: "flex",
	flexDirection: "column",
	flexShrink: 0,
	height: "100%",
	justifyContent: "flex-start",
	position: "static",
	width: "100%",
}

export function buildRootBlock(children: ManifestBlock[]): ManifestBlock {
	return {
		componentId: "root",
		componentName: "div",
		originalElement: "body",
		blockName: "body",
		baseStyles: { ...BODY_STYLES },
		classes: [],
		children,
	}
}

export interface CopyConfig {
	crmSrc: string // absolute path to crm/frontend/src
	appPath: string // absolute path to crm app root (where studio/ lives)
	studioApp: string // studio app name, e.g. "crm"
}

export function copyCustomComponents(
	components: Map<string, string>,
	config: CopyConfig,
	report: ImportNote[],
): CustomComponentRecord[] {
	const destDir = join(config.appPath, "studio", config.studioApp, "components")
	const records: CustomComponentRecord[] = []

	for (const [name, importSource] of components) {
		const source = resolveSource(importSource, config.crmSrc)
		const record: CustomComponentRecord = {
			component_name: name,
			source_path: source || "",
			dest_path: join(destDir, `${name}.vue`),
			copied: false,
		}

		if (source && existsSync(source)) {
			mkdirSync(destDir, { recursive: true })
			copyFileSync(source, record.dest_path)
			record.copied = true
			record.note = "Copied as-is; aliased (@/) imports and CRM stores inside it will not resolve in Studio's runtime until ported."
		} else {
			record.note = `Source not found for import "${importSource}"; skipped copy.`
			report.push({ page: "*", kind: "unsupported", detail: `custom component ${name}: ${record.note}` })
		}
		records.push(record)
	}
	return records
}

function resolveSource(importSource: string, crmSrc: string): string | null {
	if (!importSource) return null
	let path: string
	if (importSource.startsWith("@/")) {
		path = join(crmSrc, importSource.slice(2))
	} else if (importSource.startsWith(".")) {
		path = join(crmSrc, importSource)
	} else {
		return null // bare module (frappe-ui etc.) - not a local SFC
	}
	if (!path.endsWith(".vue")) path += ".vue"
	return path
}

export { basename, dirname }
