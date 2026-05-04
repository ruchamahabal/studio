/**
 * Build all *.studio.js bundles across all Frappe apps.
 *
 * Discovers entry files in each app's studio/ directory, builds them in parallel
 * with Vite, and writes a studio-assets.json manifest per app.
 *
 * Shared dependencies (vue, frappe-ui, vue-router) are resolved from Studio's
 * own node_modules regardless of where the entry file lives, equivalent to
 * esbuild's nodePaths. They are bundled into each output file.
 *
 * Called by `yarn build-studio-bundles` (invoked from Python's after_build hook).
 */
import fs from "fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { build } from "vite"
import frappeui from "frappe-ui/vite"
import vue from "@vitejs/plugin-vue"

const __dirname = fileURLToPath(new URL(".", import.meta.url))
// __dirname = apps/studio/frontend/src/scripts/
const STUDIO_ROOT = path.resolve(__dirname, "../../../")

// Setting Vite's root to STUDIO_FRONTEND makes its resolver walk up from
// apps/studio/frontend/ → apps/studio/node_modules/ where the correct copies
// of vue, vue-router, and frappe-ui live, with browser export conditions applied.
// Studio bundles only use shared packages + local relative imports, so app-specific
// packages from other apps' node_modules are not needed.
const STUDIO_FRONTEND = path.resolve(STUDIO_ROOT, "frontend")

// STUDIO_ROOT = apps/studio, so apps/ is one level up
const APPS_PATH = process.env.FRAPPE_BENCH_ROOT
	? path.resolve(process.env.FRAPPE_BENCH_ROOT, "apps")
	: path.resolve(STUDIO_ROOT, "..")

// --- App discovery ---

function getAppsList() {
	const apps = []
	for (const entry of fs.readdirSync(APPS_PATH)) {
		const appPath = path.resolve(APPS_PATH, entry)
		const hooksPath = path.resolve(appPath, entry, "hooks.py")
		if (fs.existsSync(hooksPath)) {
			apps.push(entry)
		}
	}
	return apps
}

function discoverEntries(apps) {
	const entries = []
	for (const app of apps) {
		const studioDir = path.resolve(APPS_PATH, app, "studio")
		if (!fs.existsSync(studioDir)) continue

		findStudioFiles(studioDir, (filePath) => {
			const entryName = path.basename(filePath, ".studio.js")
			entries.push({ app, entryName, entryPath: filePath })
		})
	}
	return entries
}

function findStudioFiles(dir, callback) {
	for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
		const fullPath = path.join(dir, entry.name)
		if (entry.isDirectory()) {
			findStudioFiles(fullPath, callback)
		} else if (entry.name.endsWith(".studio.js")) {
			callback(fullPath)
		}
	}
}

// --- Build ---

/**
 * Build a single *.studio.js entry with Vite.
 *
 * root is set to STUDIO_FRONTEND so Vite resolves bare imports (vue, frappe-ui,
 * etc.) from apps/studio/node_modules/ with browser export conditions, regardless
 * of where the entry file lives. Relative imports in the entry files resolve
 * relative to the importer file, so they are unaffected by root.
 */
async function buildEntry({ app, entryName, entryPath }) {
	const outDir = path.resolve(APPS_PATH, app, app, "public", "dist", "studio")
	const basePath = `/assets/${app}/dist/studio/`

	fs.mkdirSync(outDir, { recursive: true })

	await build({
		root: STUDIO_FRONTEND,
		base: basePath,
		configFile: false,
		define: {
			"process.env.NODE_ENV": JSON.stringify("production"),
		},
		plugins: [
			vue(),
			frappeui({
				frappeProxy: true,
				lucideIcons: true,
				buildConfig: false,
				jinjaBootData: false,
			}),
		],
		resolve: {
			// Force these packages to always resolve from root (STUDIO_FRONTEND)
			// even when the importer lives inside another app's directory.
			// This is the Vite-native equivalent of esbuild's nodePaths.
			dedupe: ["vue", "vue-router", "frappe-ui"],
		},
		build: {
			manifest: `${entryName}.manifest.json`,
			lib: {
				entry: entryPath,
				formats: ["es"],
				fileName: entryName,
			},
			outDir,
			emptyOutDir: false,
			target: "es2015",
			sourcemap: true,
			chunkSizeWarningLimit: 1000,
		},
		logLevel: "warn",
	})
}

// --- Manifest ---

function writeStudioAssetsJson(appEntries) {
	const entriesByApp = {}
	for (const entry of appEntries) {
		if (!entriesByApp[entry.app]) entriesByApp[entry.app] = []
		entriesByApp[entry.app].push(entry)
	}

	for (const [app, entries] of Object.entries(entriesByApp)) {
		const outDir = path.resolve(APPS_PATH, app, app, "public", "dist", "studio")
		const studioAssets = {}

		for (const { entryName } of entries) {
			const manifestPath = path.join(outDir, `${entryName}.manifest.json`)
			if (!fs.existsSync(manifestPath)) continue

			const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf-8"))
			for (const [, value] of Object.entries(manifest)) {
				if (value.isEntry) {
					studioAssets[entryName] = value.file
					break
				}
			}
			fs.unlinkSync(manifestPath)
		}

		if (Object.keys(studioAssets).length > 0) {
			const assetsJsonPath = path.join(outDir, "studio-assets.json")
			fs.writeFileSync(assetsJsonPath, JSON.stringify(studioAssets, null, 2))
			console.log(`  ${app}/public/dist/studio/studio-assets.json`)
		}
	}
}

// --- Main ---

const TOTAL_BUILD_TIME = "Studio Bundles Build Time"
console.time(TOTAL_BUILD_TIME)

const apps = getAppsList()
const entries = discoverEntries(apps)

if (entries.length === 0) {
	console.log("No *.studio.js bundles found.")
	console.timeEnd(TOTAL_BUILD_TIME)
	process.exit(0)
}

console.log(`Found ${entries.length} studio bundle(s):`)
for (const entry of entries) {
	console.log(`  ${entry.app}: ${path.basename(entry.entryPath)}`)
}
console.log("")

// Build all entries in parallel
const results = await Promise.allSettled(entries.map((entry) => buildEntry(entry)))

let hasErrors = false
for (let i = 0; i < results.length; i++) {
	const entry = entries[i]
	const result = results[i]
	if (result.status === "fulfilled") {
		console.log(`  ✔ ${entry.app}/${entry.entryName}`)
	} else {
		hasErrors = true
		console.error(`  ✖ ${entry.app}/${entry.entryName}: ${result.reason?.message || result.reason}`)
	}
}

const successfulEntries = entries.filter((_, i) => results[i].status === "fulfilled")
if (successfulEntries.length > 0) {
	console.log("\nManifests:")
	writeStudioAssetsJson(successfulEntries)
}

console.log("")
console.timeEnd(TOTAL_BUILD_TIME)

if (hasErrors) {
	process.exit(1)
}
