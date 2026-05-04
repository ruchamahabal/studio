import fs from "fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { build } from "vite"
import vue from "@vitejs/plugin-vue"
import frappeui from "frappe-ui/vite"
import { esmExternalRequirePlugin } from "rolldown/plugins"

const __dirname = fileURLToPath(new URL(".", import.meta.url))
const STUDIO_ROOT = path.resolve(__dirname, "../../../")
const APPS_PATH = process.env.FRAPPE_BENCH_ROOT
	? path.resolve(process.env.FRAPPE_BENCH_ROOT, "apps")
	: path.resolve(STUDIO_ROOT, "..")

const outDir = path.resolve(APPS_PATH, "studio", "studio", "public", "dist", "shared")

async function buildSharedDeps() {
	console.time("Shared Deps Build Time")
	console.log(`Building shared dependencies to ${outDir}...`)
	fs.mkdirSync(outDir, { recursive: true })

	const buildConfig = (name, entry, external = []) => ({
		configFile: false,
		define: {
			"process.env.NODE_ENV": JSON.stringify("production"),
		},
		plugins: [
			frappeui({
				frappeProxy: true,
				lucideIcons: true,
				buildConfig: false,
				jinjaBootData: false,
			}),
			vue(),
			esmExternalRequirePlugin({ external }),
		],
		build: {
			outDir,
			emptyOutDir: false,
			lib: {
				entry: entry,
				formats: ["es"],
				fileName: () => `${name}.js`,
			},
			target: "es2015",
			sourcemap: true,
			minify: true,
		},
		logLevel: "warn",
	})

	const tmpDir = path.resolve(__dirname, "tmp_shared_entries")
	fs.mkdirSync(tmpDir, { recursive: true })

	function createEntry(name, importPath) {
		const entryPath = path.resolve(tmpDir, `${name}.js`)
		fs.writeFileSync(entryPath, `export * from "${importPath}";`)
		return entryPath
	}

	console.log("  Building vue...")
	await build(buildConfig("vue", createEntry("vue", "vue")))

	console.log("  Building vue-router...")
	await build(buildConfig("vue-router", createEntry("vue-router", "vue-router"), ["vue"]))

	console.log("  Building frappe-ui...")
	await build(buildConfig("frappe-ui", createEntry("frappe-ui", "frappe-ui"), ["vue", "vue-router"]))

	console.log("  Building frappe-ui/frappe...")
	await build(
		buildConfig("frappe-ui-frappe", createEntry("frappe-ui-frappe", "frappe-ui/frappe"), [
			"vue",
			"vue-router",
			"frappe-ui",
		]),
	)

	console.log("  Building frappe-ui/icons...")
	await build(
		buildConfig("frappe-ui-icons", createEntry("frappe-ui-icons", "frappe-ui/icons"), [
			"vue",
			"vue-router",
			"frappe-ui",
		]),
	)

	fs.rmSync(tmpDir, { recursive: true, force: true })
	console.log("Done!")
	console.timeEnd("Shared Deps Build Time")
}

buildSharedDeps().catch(console.error)
