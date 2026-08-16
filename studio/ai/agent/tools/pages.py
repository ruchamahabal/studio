"""App-wide page tools: browse the app's pages and move the turn's focus.

The agent edits ONE page at a time — its focus. `list_pages`/`read_page` give it
app-level awareness (routes, digests of sibling pages) without moving the focus;
`open_page`/`create_page` move it: the runner re-points its working tree, toolset
and per-page run lock at the target (see AgentRunner.focus_page), and every block
op after that lands on the new page. The editor mirrors only events for the page
it shows, so background pages build quietly and appear from the DB on navigation.
"""

import json

import frappe

from studio.ai.agent.registry import Tool
from studio.ai.block_codec import BlockCodec

# Matches the editor's "body" block template (frontend/src/utils/blockTemplate).
STARTER_ROOT = {
	"componentId": "root",
	"componentName": "div",
	"blockName": "body",
	"originalElement": "body",
	"children": [],
	"baseStyles": {
		"display": "flex",
		"flexDirection": "row",
		"flexShrink": 0,
		"width": "inherit",
		"overflowX": "hidden",
		"height": "100%",
	},
}


def run_list_pages(ctx, args: dict) -> str:
	if not ctx.app_id:
		return "FAILED: this chat is not attached to an app."
	pages = frappe.get_all(
		"Studio Page",
		filters={"studio_app": ctx.app_id},
		fields=["name", "page_title", "route", "published"],
		order_by="creation asc",
	)
	for page in pages:
		if page["name"] == ctx.page_id:
			page["focused"] = True
	return f"Pages in this app ('name' is what open_page/read_page take):\n{BlockCodec.to_json(pages)}"


def run_read_page(ctx, args: dict) -> str:
	page, error = _resolve_app_page(ctx, args.get("page_name"))
	if error:
		return error
	if page.name == ctx.page_id:
		return "That's the focused page — its structure is already in your context (or query_blocks it)."
	return f"Page '{page.name}' ({page.page_title}, route {page.route}):\n{_page_digest(page)}"


def run_open_page(ctx, args: dict) -> str:
	page, error = _resolve_app_page(ctx, args.get("page_name"))
	if error:
		return error
	if page.name == ctx.page_id:
		return f"Already focused on '{page.name}'."
	if error := ctx.focus_page(page.name):
		return f"FAILED: {error}"
	ctx.emit("progress", message=f"Working on page '{page.page_title}'…")
	return (
		f"Focused on page '{page.name}' ({page.page_title}, route {page.route}). All block "
		f"edits now target THIS page. Current structure:\n{_focused_tree_json(ctx)}"
	)


def run_create_page(ctx, args: dict) -> str:
	if not ctx.app_id:
		return "FAILED: this chat is not attached to an app."
	title = (args.get("title") or "").strip()
	if not title:
		return "FAILED: 'title' is required."
	route = _normalize_route(args.get("route") or "")
	if route and frappe.db.exists("Studio Page", {"studio_app": ctx.app_id, "route": route}):
		return f"FAILED: route '{route}' already exists in this app — pick another or open that page."

	is_standard, frappe_app = frappe.db.get_value("Studio App", ctx.app_id, ["is_standard", "frappe_app"])
	page = frappe.get_doc(
		{
			"doctype": "Studio Page",
			"studio_app": ctx.app_id,
			"page_title": title,
			"route": route or None,
			"draft_blocks": [STARTER_ROOT],
			"is_standard": is_standard,
			"frappe_app": frappe_app if is_standard else None,
		}
	)
	page.insert(ignore_permissions=False)
	frappe.db.commit()

	if error := ctx.focus_page(page.name):
		return f"Created page '{page.name}' ({page.route}), but could not focus it: {error}"
	ctx.emit("progress", message=f"Created page '{page.page_title}' — building it…")
	return (
		f"Created page '{page.name}' ({page.page_title}, route {page.route}) and focused it. "
		"It's empty (a bare body block) — build it now: all block edits target THIS page."
	)


def _resolve_app_page(ctx, page_name):
	"""The named page as a doc, verified to exist in this chat's app. Returns
	(page, None) or (None, error_string)."""
	page_name = (page_name or "").strip()
	if not page_name:
		return None, "FAILED: 'page_name' is required — get it from list_pages."
	if not ctx.app_id:
		return None, "FAILED: this chat is not attached to an app."
	if not frappe.db.exists("Studio Page", {"name": page_name, "studio_app": ctx.app_id}):
		return None, f"FAILED: no page '{page_name}' in this app — call list_pages for real names."
	return frappe.get_doc("Studio Page", page_name), None


def _page_digest(page) -> str:
	"""A page's block tree in the same compact schema as the focused page's context."""
	try:
		data = json.loads(page.draft_blocks or page.blocks or "[]")
	except (json.JSONDecodeError, TypeError):
		return "(unreadable page)"
	root = data[0] if isinstance(data, list) and data else data
	if not isinstance(root, dict):
		return "(empty page)"
	return BlockCodec.to_json(BlockCodec.compress(root))


def _focused_tree_json(ctx) -> str:
	root = ctx.page_root()
	return BlockCodec.to_json(BlockCodec.compress(root)) if root else "(empty page)"


def _normalize_route(route: str) -> str:
	route = route.strip()
	if route and not route.startswith("/"):
		route = f"/{route}"
	return route


list_pages = Tool(
	name="list_pages",
	side="server",
	handler=run_list_pages,
	description=(
		"List every page in this app: name (the ref open_page/read_page take), title, route, and "
		"published state. Call this before referencing, linking to, or editing another page."
	),
	parameters={"type": "object", "properties": {}},
)

read_page = Tool(
	name="read_page",
	side="server",
	handler=run_read_page,
	description=(
		"Read another page's block structure (compact schema, same as your page context) WITHOUT "
		"switching to it. Use it to match an existing page's design, reuse its patterns, or check "
		"what a route renders before linking to it."
	),
	parameters={
		"type": "object",
		"properties": {
			"page_name": {"type": "string", "description": "The page's 'name' from list_pages."},
		},
		"required": ["page_name"],
	},
)

open_page = Tool(
	name="open_page",
	side="server",
	handler=run_open_page,
	description=(
		"Switch your working focus to another EXISTING page in this app. After this, ALL block "
		"edits (add/update/move/generate_page/bindings/script) target that page until you switch "
		"again. Work on ONE page at a time, finishing it before moving on. The user's editor is "
		"unaffected — they see the result when they open that page."
	),
	parameters={
		"type": "object",
		"properties": {
			"page_name": {"type": "string", "description": "The page's 'name' from list_pages."},
		},
		"required": ["page_name"],
	},
)

create_page = Tool(
	name="create_page",
	side="server",
	handler=run_create_page,
	description=(
		"Create a NEW page in this app and switch your working focus to it. Use when the user asks "
		"for a page that doesn't exist yet (check list_pages first). Give a clear title and a short "
		"kebab-case route (e.g. '/orders'); the route must be unique within the app. The new page "
		"starts empty — build it right after, and wire navigation to it from other pages if asked."
	),
	parameters={
		"type": "object",
		"properties": {
			"title": {"type": "string", "description": "Human page title, e.g. 'Order History'."},
			"route": {
				"type": "string",
				"description": "URL route within the app, e.g. '/orders'. Optional — derived from the title if omitted.",
			},
		},
		"required": ["title"],
	},
)

TOOLS = [list_pages, read_page, open_page, create_page]
