/**
 * Build all standard (exported) Studio apps from disk.
 *
 * This script scans all `apps/<app_name>/studio/` folders, reads the exported
 * page JSONs, extracts the component names, and builds each app using Vite.
 *
 * Designed to run during `bench build --app studio` without a DB connection.
 */
import fs from "fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { generateAppBuild, findComponentSources } from "./build.js"
import { FRAPPE_UI_COMPONENTS, FRAPPE_COMPONENTS, STUDIO_COMPONENTS } from "../utils/constants.js"

const __dirname = fileURLToPath(new URL(".", import.meta.url))

// apps/ directory (bench-level)
const APPS_DIR = path.resolve(__dirname, "../../../../")

// components that are not actual Vue components
const NON_VUE_COMPONENTS = ["div", "container"]
// default components always included
const DEFAULT_COMPONENTS = ["FeatherIcon"]

/**
 * Discover all standard studio apps across all bench apps.
 * Structure: apps/{frappe_app}/studio/{app_name}/{app_name}.json
 */
function discoverStandardApps() {
	const apps = []

	if (!fs.existsSync(APPS_DIR)) {
		console.warn(`Apps directory not found: ${APPS_DIR}`)
		return apps
	}

	for (const frappeApp of fs.readdirSync(APPS_DIR)) {
		const studioFolder = path.join(APPS_DIR, frappeApp, "studio")
		if (!fs.existsSync(studioFolder) || !fs.statSync(studioFolder).isDirectory()) {
			continue
		}

		// For the 'studio' app itself, read studio_apps.txt to know which folders to process
		let studioAppFolders
		if (frappeApp === "studio") {
			const studioAppsTxtPath = path.join(APPS_DIR, "studio", "studio", "studio_apps.txt")
			if (fs.existsSync(studioAppsTxtPath)) {
				const content = fs.readFileSync(studioAppsTxtPath, "utf-8")
				studioAppFolders = content
					.split("\n")
					.map((line) => line.trim())
					.filter(Boolean)
			} else {
				studioAppFolders = []
			}
		} else {
			studioAppFolders = fs.readdirSync(studioFolder).filter((item) => {
				return fs.statSync(path.join(studioFolder, item)).isDirectory()
			})
		}

		for (const appFolder of studioAppFolders) {
			const appFolderPath = path.join(studioFolder, appFolder)
			const appJsonPath = path.join(appFolderPath, `${appFolder}.json`)

			if (!fs.existsSync(appJsonPath)) {
				continue
			}

			try {
				const appData = JSON.parse(fs.readFileSync(appJsonPath, "utf-8"))
				if (appData.is_standard) {
					apps.push({
						name: appData.name,
						frappeApp: appData.frappe_app || frappeApp,
						folderPath: appFolderPath,
					})
				}
			} catch (e) {
				console.warn(`Could not parse ${appJsonPath}: ${e.message}`)
			}
		}
	}

	return apps
}

/**
 * Extract all component names used across pages of a studio app (from disk).
 * Mirrors the Python `get_app_components` logic in studio/api.py.
 */
function extractComponentsFromDisk(appFolderPath) {
	const components = new Set(DEFAULT_COMPONENTS)

	// Read all page JSON files
	const pagesFolder = path.join(appFolderPath, "studio_page")
	if (!fs.existsSync(pagesFolder)) {
		return components
	}

	// Load studio components from disk for recursive resolution
	const studioComponentsMap = loadStudioComponentsFromDisk(appFolderPath)

	const pageFiles = fs.readdirSync(pagesFolder).filter((f) => f.endsWith(".json"))
	for (const pageFile of pageFiles) {
		try {
			const pageData = JSON.parse(fs.readFileSync(path.join(pagesFolder, pageFile), "utf-8"))
			const blocks = pageData.blocks
			if (!blocks) continue

			const parsedBlocks = typeof blocks === "string" ? JSON.parse(blocks) : blocks

			// Extract h() function component references
			if (typeof blocks === "string") {
				extractHFunctionComponents(blocks, components)
			}

			if (Array.isArray(parsedBlocks) && parsedBlocks.length > 0) {
				extractBlockComponents(parsedBlocks[0], components, studioComponentsMap)
			}
		} catch (e) {
			console.warn(`Could not parse page ${pageFile}: ${e.message}`)
		}
	}

	return components
}

/**
 * Load studio component definitions from the studio_components/ folder on disk.
 * Returns a map of component name -> block definition.
 */
function loadStudioComponentsFromDisk(appFolderPath) {
	const componentsMap = new Map()
	const componentsFolder = path.join(appFolderPath, "studio_components")

	if (!fs.existsSync(componentsFolder)) {
		return componentsMap
	}

	const componentFiles = fs.readdirSync(componentsFolder).filter((f) => f.endsWith(".json"))
	for (const componentFile of componentFiles) {
		try {
			const componentData = JSON.parse(fs.readFileSync(path.join(componentsFolder, componentFile), "utf-8"))
			if (componentData.name && componentData.block) {
				const block =
					typeof componentData.block === "string" ? JSON.parse(componentData.block) : componentData.block
				componentsMap.set(componentData.name, block)
			}
		} catch (e) {
			console.warn(`Could not parse component ${componentFile}: ${e.message}`)
		}
	}

	return componentsMap
}

/**
 * Extract component names from h(ComponentName...) function calls in text.
 */
function extractHFunctionComponents(text, components) {
	const pattern = /\bh\(\s*([A-Z][a-zA-Z0-9_]*)/g
	let match
	while ((match = pattern.exec(text)) !== null) {
		components.add(match[1])
	}
}

/**
 * Recursively extract component names from a block tree.
 */
function extractBlockComponents(block, components, studioComponentsMap) {
	if (!block) return

	if (block.isStudioComponent) {
		// Resolve the studio component's own block definition
		const componentBlock = studioComponentsMap.get(block.componentName)
		if (componentBlock) {
			extractBlockComponents(componentBlock, components, studioComponentsMap)
		}
	} else if (block.componentName && !NON_VUE_COMPONENTS.includes(block.componentName)) {
		components.add(block.componentName)
	}

	// Process children
	if (Array.isArray(block.children)) {
		for (const child of block.children) {
			extractBlockComponents(child, components, studioComponentsMap)
		}
	}

	// Process component slots
	if (block.componentSlots) {
		for (const slot of Object.values(block.componentSlots)) {
			if (typeof slot.slotContent === "string") continue
			if (Array.isArray(slot.slotContent)) {
				for (const slotChild of slot.slotContent) {
					extractBlockComponents(slotChild, components, studioComponentsMap)
				}
			}
		}
	}
}

// --- Main ---

async function main() {
	console.log("Discovering standard Studio apps from disk...")
	const standardApps = discoverStandardApps()

	if (standardApps.length === 0) {
		console.log("No standard Studio apps found.")
		return
	}

	console.log(`Found ${standardApps.length} standard app(s):`)
	for (const app of standardApps) {
		console.log(`  - ${app.name} (frappe_app: ${app.frappeApp})`)
	}

	for (const app of standardApps) {
		const components = extractComponentsFromDisk(app.folderPath)
		if (components.size === 0) {
			console.log(`Skipping ${app.name}: no components found.`)
			continue
		}

		console.log(`\nBuilding ${app.name} (${components.size} components)...`)

		// Output to the target frappe app's public/app_builds/ folder
		const outDir = path.join(APPS_DIR, app.frappeApp, app.frappeApp, "public", "app_builds", app.name)
		const basePath = `/assets/${app.frappeApp}/app_builds/${app.name}/`

		try {
			await generateAppBuild(app.name, [...components].join(","), {
				outDir,
				basePath,
			})
			console.log(`✓ Built ${app.name}`)
		} catch (e) {
			console.error(`✗ Failed to build ${app.name}: ${e.message}`)
		}
	}
}

main().catch((e) => {
	console.error("Build failed:", e)
	process.exit(1)
})
