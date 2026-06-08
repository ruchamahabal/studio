// CLI entry for the Vue -> Studio importer.
//
// Usage (from studio/frontend):
//   node_modules/.bin/tsx src/importer/cli.ts \
//     --crm <abs path to crm app root> \
//     --out <abs path for studio-manifest.json>
//
// Milestone 1 imports the CRM Contacts list page.

import { writeFileSync } from "node:fs"
import { join } from "node:path"

import { importApp, type PageSpec } from "./importApp"

// Milestone 1 page set. Add more PageSpecs here as coverage grows.
const CRM_PAGES: PageSpec[] = [
	{ page_title: "Contacts", route: "/contacts", file: "pages/Contacts.vue" },
]

function parseArgs(argv: string[]): Record<string, string> {
	const args: Record<string, string> = {}
	for (let i = 0; i < argv.length; i += 2) {
		const key = argv[i].replace(/^--/, "")
		args[key] = argv[i + 1]
	}
	return args
}

function main() {
	const args = parseArgs(process.argv.slice(2))
	const crmApp = args.crm || "/Users/ruchamahabal/bench-v16/apps/crm"
	const out = args.out || join(process.cwd(), "studio-manifest.json")

	const manifest = importApp({
		app_name: "crm",
		app_title: "CRM",
		frappe_app: "crm",
		crmSrc: join(crmApp, "frontend", "src"),
		appPath: crmApp,
		pages: CRM_PAGES,
	})

	writeFileSync(out, JSON.stringify(manifest, null, 2))

	const reportPath = out.replace(/\.json$/, "") + "-report.json"
	writeFileSync(reportPath, JSON.stringify(manifest.report, null, 2))

	console.log(`Manifest written to ${out}`)
	console.log(`Pages: ${manifest.pages.length}, custom components: ${manifest.custom_components.length}`)
	console.log(`Report notes: ${manifest.report.length} (see ${reportPath})`)
}

main()
