import vue from "@vitejs/plugin-vue"
import frappeui from "frappe-ui/vite"
import path from "path"
import fs from "fs"
import { defineConfig } from "vite"

const STUDIO_ROOT = path.resolve(__dirname, "..")

/**
 * Vite plugin to redirect shared dependency imports from custom Vue components
 * (files outside the Studio project) to Studio's own installations.
 *
 * These are singleton deps (vue, vue-router, frappe-ui) that must resolve from
 * Studio to avoid duplicate instances. App-specific deps
 * resolve normally from the app's own node_modules.
 */
const STUDIO_SHARED_DEPS = ["vue", "vue-router", "frappe-ui"]

function studioDepsResolver() {
	return {
		name: "studio-deps-resolver",
		enforce: "pre",
		async resolveId(source, importer, options) {
			// Only intercept shared deps
			if (!STUDIO_SHARED_DEPS.some((dep) => source === dep || source.startsWith(dep + "/"))) return null
			// Only intercept if the importer is outside Studio's project
			if (!importer || importer.startsWith(STUDIO_ROOT)) return null

			// Re-resolve from Studio's project root so Vite finds the right copy
			const resolved = await this.resolve(source, path.join(STUDIO_ROOT, "frontend", "_virtual.js"), {
				...options,
				skipSelf: true,
			})
			return resolved
		},
	}
}

/**
 * Vite plugin to discover and pre-build custom Vue components from all
 * installed Frappe apps. Components are exposed via a virtual module
 * `virtual:custom-components` as lazy barrel-module loaders, allowing them
 * to be code-split into separate chunks that share the same Vue instance.
 *
 * Convention: each studio app exposes a barrel file at
 *   apps/{app}/studio/{studio_app}/components.js (or .ts)
 * that re-exports its custom Vue components:
 *   export { default as EmojiCard } from "./components/EmojiCard.vue"
 *
 * The virtual module maps barrel keys ("{app}/{studioApp}") to lazy loaders.
 */
function studioCustomComponentsPlugin() {
	const VIRTUAL_ID = "virtual:custom-components"
	const RESOLVED_ID = "\0" + VIRTUAL_ID

	const appsDir = path.resolve(__dirname, "../../")
	const barrels = discoverComponentBarrels(appsDir)

	if (Object.keys(barrels).length > 0) {
		console.log(`[studio] Discovered component barrels: ${Object.keys(barrels).join(", ")}`)
	}

	return {
		name: "studio-custom-components",
		resolveId(id) {
			if (id === VIRTUAL_ID) return RESOLVED_ID
		},
		load(id) {
			if (id !== RESOLVED_ID) return null

			const entries = Object.entries(barrels)
			if (entries.length === 0) {
				return "export default {}"
			}

			const imports = entries.map(([key, filePath]) => `  "${key}": () => import("${filePath}")`).join(",\n")

			return `export default {\n${imports}\n}`
		},
	}
}

/**
 * Scan all apps in the bench for component barrel files.
 * Looks for: apps/{app_name}/studio/{studio_app}/components.{js,ts}
 *
 * Returns a map of { "{app_name}/{studio_app}": absoluteBarrelPath }
 */
function discoverComponentBarrels(appsDir) {
	const barrels = {}

	let appNames
	try {
		appNames = fs.readdirSync(appsDir)
	} catch {
		return barrels
	}

	for (const appName of appNames) {
		const studioFolder = path.join(appsDir, appName, "studio")

		let studioApps
		try {
			if (!fs.statSync(studioFolder).isDirectory()) continue
			studioApps = fs.readdirSync(studioFolder)
		} catch {
			continue
		}

		for (const studioApp of studioApps) {
			const studioAppDir = path.join(studioFolder, studioApp)
			try {
				if (!fs.statSync(studioAppDir).isDirectory()) continue
			} catch {
				continue
			}

			// Look for components.js or components.ts
			for (const ext of [".js", ".ts"]) {
				const barrelPath = path.join(studioAppDir, `components${ext}`)
				if (fs.existsSync(barrelPath)) {
					barrels[`${appName}/${studioApp}`] = barrelPath
					break // prefer .js over .ts if both exist
				}
			}
		}
	}

	return barrels
}

// https://vitejs.dev/config/
export default defineConfig({
	define: {
		__VUE_PROD_HYDRATION_MISMATCH_DETAILS__: false,
		__VUE_PROD_DEVTOOLS__: true,
	},
	server: {
		// explicitly set origin of generated assets (images, fonts, etc) during development.
		// Required for the app renderer running on webserver port
		// https://vite.dev/guide/backend-integration
		origin: "http://127.0.0.1:8086",
		allowedHosts: true,
		// Allow cross-origin requests from the renderer running on webserver port to Vite dev server.
		cors: true,
		fs: {
			// Allow serving files from other apps in the bench (for custom Vue components)
			allow: [path.resolve(__dirname, ".."), path.resolve(__dirname, "../../../")],
		},
		watch: {
			// unplugin-vue-components generates this file which causes HMR while building other studio apps
			ignored: ["**/components.d.ts", "**/auto-imports.d.ts"],
		},
	},
	plugins: [
		frappeui({
			frappeProxy: true,
			lucideIcons: true,
			buildConfig: false,
			jinjaBootData: false,
		}),
		vue(),
		// Redirect frappe-ui imports from custom Vue components (outside Studio's project)
		// to Studio's copy, so they don't resolve to a different/incomplete installation.
		studioDepsResolver(),
		// Pre-build custom Vue components from installed Frappe apps into code-split chunks
		studioCustomComponentsPlugin(),
	],
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
		},
	},
	build: {
		rollupOptions: {
			input: {
				studio: path.resolve(__dirname, "index.html"),
				renderer: path.resolve(__dirname, "renderer.html"),
			},
		},
		outDir: `../studio/public/frontend`,
		emptyOutDir: true,
		target: "es2015",
		sourcemap: true,
		chunkSizeWarningLimit: 1000,
	},
	optimizeDeps: {
		include: [
			"feather-icons",
			"showdown",
			"engine.io-client",
			"highlight.js/lib/core",
			"interactjs",
			"debug",
		],
	},
})
