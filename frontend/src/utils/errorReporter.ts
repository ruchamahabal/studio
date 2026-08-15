/** Report uncaught renderer errors to the AI agent's per-page error ring.
 *
 * Active only on the /dev preview — that's what the agent screenshots and what
 * the developer watches while building. The agent reads (and clears) these via
 * its get_page_errors tool, so broken bindings and crashed setups become
 * fixable feedback instead of silent blank areas.
 */

const REPORT_LIMIT = 10

let reported = 0

export function installErrorReporter(app: any) {
	if (!window.is_preview) return

	app.config.errorHandler = (err: any, _instance: any, info: string) => {
		report(String(err?.message || err), info, String(err?.stack || ""))
		console.error(err)
	}
	window.addEventListener("error", (event) => {
		report(event.message, event.filename || "", String(event.error?.stack || ""))
	})
	window.addEventListener("unhandledrejection", (event) => {
		const reason: any = event.reason
		report(`Unhandled rejection: ${reason?.message || reason}`, "", String(reason?.stack || ""))
	})
}

function report(message: string, source: string, stack: string) {
	if (!message || reported >= REPORT_LIMIT) return
	reported += 1
	const pageId = currentPageId()
	if (!pageId) return
	fetch("/api/method/studio.ai.api.report_page_error", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": (window as any).csrf_token || "",
		},
		body: JSON.stringify({ page_id: pageId, message, source, stack }),
	}).catch(() => {})
}

function currentPageId(): string {
	const pages = window.app_pages || []
	const path = normalize(stripBase(window.location.pathname))
	const match =
		pages.find((p) => normalize(p.route) === path) ||
		// dynamic routes (/orders/:id) — match on the static prefix
		pages.find((p) => {
			const prefix = normalize(p.route.split("/:")[0])
			return prefix && path.startsWith(prefix)
		})
	return match?.name || ""
}

function stripBase(path: string): string {
	const base = `/${window.app_route}`
	return path.startsWith(base) ? path.slice(base.length) : path
}

function normalize(route: string): string {
	const cleaned = `/${(route || "").replace(/^\/+|\/+$/g, "")}`
	return cleaned === "//" ? "/" : cleaned
}
