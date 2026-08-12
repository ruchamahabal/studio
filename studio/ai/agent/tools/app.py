"""App-scope tools — let the agent work on the WHOLE app, not just the open page.

The canvas (and every client block tool) stays bound to the page open in the
editor; these server tools give the agent the rest of the app: the map of pages
and routes, sibling pages' content, page creation, and full server-side page
generation. A sibling page built here is saved as that page's draft — the editor
and preview pick it up through the normal `studio_doc_update` realtime sync, and
the user can open the page to refine it with the ordinary point-and-edit flow.

Data sources / variables / scripts on sibling pages are handled by the existing
tools via their optional `page_name` argument (see tools/page.py) — build order
stays backend-first there too: create the page, wire its data, then build it.
"""

import frappe

from studio.ai.agent.registry import Tool
from studio.ai.agent.tools.introspect import describe_page_data
from studio.ai.agent.tools.page import NO_PAGE, is_sibling_page, load_page, text_arg
from studio.ai.block_codec import BlockCodec

_PAGE_FIELDS = ["name", "page_title", "route", "published", "modified"]


def run_get_app_map(ctx, args: dict) -> str:
	app = _studio_app(ctx)
	if not app:
		return "No app in context."
	doc = frappe.get_doc("Studio App", app)
	pages = frappe.get_all(
		"Studio Page", filters={"studio_app": app}, fields=_PAGE_FIELDS, order_by="creation asc"
	)
	for page in pages:
		page["is_home"] = page["name"] == doc.app_home
		page.pop("modified", None)
	out = {
		"app": app,
		"title": doc.app_title,
		"route": f"/{doc.route}" if doc.route else "",
		"is_standard": bool(doc.is_standard),
		"current_page": ctx.page_id,
		"pages": pages,
	}
	return (
		"App map (page 'name' is the id for page_name/read_app_page/build_app_page; "
		"'route' is what navigation links use):\n" + BlockCodec.to_json(out)
	)


def run_read_app_page(ctx, args: dict) -> str:
	page = load_page(ctx, args)
	if page is None:
		return f"FAILED: {NO_PAGE}"
	root = _page_root(page)
	out = {
		"page": page.name,
		"title": page.page_title,
		"route": page.route,
		**describe_page_data(page),
		"blocks": BlockCodec.compress(root) if root else None,
	}
	return f"Page {page.name}:\n" + BlockCodec.to_json(out)


def run_create_app_page(ctx, args: dict) -> str:
	app = _studio_app(ctx)
	if not app:
		return "FAILED: no app in context."
	title = text_arg(args.get("page_title"))
	if not title:
		return "FAILED: page_title is required."
	if not frappe.has_permission("Studio Page", "create"):
		return "FAILED: you do not have permission to create pages."
	page = frappe.get_doc(
		{
			"doctype": "Studio Page",
			"studio_app": app,
			"page_title": title,
			"route": text_arg(args.get("route")) or None,
		}
	).insert()
	frappe.db.commit()
	return (
		f"Created page '{title}' (name={page.name}, route={page.route}). Wire its data with the "
		f"data/variable/script tools using page_name='{page.name}', then build it with build_app_page."
	)


def run_build_app_page(ctx, args: dict) -> str:
	from studio.ai.agent.artifact import generate_blocks

	page = load_page(ctx, args)
	if page is None:
		return f"FAILED: {NO_PAGE}"
	if page.name == ctx.page_id:
		return "FAILED: this is the page open in the editor — build it with generate_page instead."
	brief = text_arg(args.get("brief"))
	if not brief:
		return "FAILED: brief is required."

	ctx.emit("progress", message=f"Building page '{page.page_title}'…")
	block = generate_blocks(ctx, page, brief)
	if block is None:
		return "FAILED: the generated page did not parse. Try again with a shorter, more specific brief."
	page.save_draft(frappe.as_json([block], indent=None))
	frappe.db.commit()
	return (
		f"Built page '{page.page_title}' ({page.route}) and saved it as a draft. The user can open it "
		"in the editor to refine, and publish when ready."
	)


def run_set_app_home(ctx, args: dict) -> str:
	app = _studio_app(ctx)
	if not app:
		return "FAILED: no app in context."
	name = text_arg(args.get("page_name"))
	if name != ctx.page_id and not is_sibling_page(ctx, name):
		return f"FAILED: {NO_PAGE}"
	frappe.db.set_value("Studio App", app, "app_home", name)
	frappe.db.commit()
	return f"Set {name} as the app's home page."


# --- helpers --------------------------------------------------------------


def _studio_app(ctx) -> str | None:
	return frappe.db.get_value("Studio Page", ctx.page_id, "studio_app") if ctx.page_id else None


def _page_root(page) -> dict | None:
	raw = page.draft_blocks or page.blocks
	try:
		data = frappe.parse_json(raw) if raw else None
	except ValueError:
		return None
	if isinstance(data, list):
		data = data[0] if data else None
	return data if isinstance(data, dict) else None


# --- tool definitions -----------------------------------------------------

_PAGE_NAME_ARG = {"type": "string", "description": "The page's id ('name' from get_app_map)."}

get_app_map = Tool(
	name="get_app_map",
	side="server",
	handler=run_get_app_map,
	description=(
		"Read the WHOLE app's structure: its title, base route, and every page (id, title, route, "
		"published, home). Call this first for any request that spans pages — building a multi-page "
		"app, wiring navigation (Sidebar/links need the real routes), or editing a page that isn't open."
	),
	parameters={"type": "object", "properties": {}},
)

read_app_page = Tool(
	name="read_app_page",
	side="server",
	handler=run_read_app_page,
	description=(
		"Read a SIBLING page of this app: its meta, data sources, variables, and full block tree. "
		"Use it to keep new pages consistent with existing ones (styling, layout patterns) or to "
		"check another page before linking to it."
	),
	parameters={
		"type": "object",
		"properties": {"page_name": _PAGE_NAME_ARG},
		"required": ["page_name"],
	},
)

create_app_page = Tool(
	name="create_app_page",
	side="server",
	handler=run_create_app_page,
	description=(
		"Create a NEW page in this app (title + optional route). Returns the page id to use as "
		"page_name in other tools. Whole-app build order: create the page, add its data sources/state "
		"with page_name, then build_app_page with a brief — and wire navigation links to its route."
	),
	parameters={
		"type": "object",
		"properties": {
			"page_title": {"type": "string", "description": "Human title, e.g. 'Order Details'."},
			"route": {
				"type": "string",
				"description": "Optional route, e.g. '/orders/:id' for a dynamic route. Auto-derived from the title when omitted.",
			},
		},
		"required": ["page_title"],
	},
)

build_app_page = Tool(
	name="build_app_page",
	side="server",
	handler=run_build_app_page,
	description=(
		"Generate a COMPLETE page layout for a sibling page (not the one open in the editor) from a "
		"concise brief, and save it as that page's draft. Create the page's data sources FIRST (with "
		"page_name) so the brief can bind to them. The brief follows the same rules as generate_page: "
		"design direction, section list with real copy intent, data bindings, palette — not JSON. For "
		"the OPEN page use generate_page instead."
	),
	parameters={
		"type": "object",
		"properties": {
			"page_name": _PAGE_NAME_ARG,
			"brief": {
				"type": "string",
				"description": "Concise spec of the page to build (same style as generate_page's brief).",
			},
		},
		"required": ["page_name", "brief"],
	},
)

set_app_home = Tool(
	name="set_app_home",
	side="server",
	handler=run_set_app_home,
	description="Make a page the app's home page (the one served at the app's base route).",
	parameters={
		"type": "object",
		"properties": {"page_name": _PAGE_NAME_ARG},
		"required": ["page_name"],
	},
)

TOOLS = [get_app_map, read_app_page, create_app_page, build_app_page, set_app_home]
