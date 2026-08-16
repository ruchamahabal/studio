"""App-wide page tools: list, read, create, open, and rename the app's pages.

Sessions are app-scoped; these tools let one conversation work across the whole
app. Every block tool works on the working page — edits are applied and saved
server-side (see WorkingTree), so it doesn't matter which page the user is
looking at. One rule stands (learned the hard way by Builder, which shipped
multi-page fan-out and reverted it): the agent builds ONE page at a time,
sequentially.
"""

import json

import frappe

from studio.ai.agent.registry import Tool


def run_list_pages(ctx, args: dict) -> str:
	if not ctx.app_id:
		return "FAILED: this chat has no app in scope."
	pages = frappe.get_all(
		"Studio Page",
		filters={"studio_app": ctx.app_id},
		fields=["name", "page_title", "route"],
		order_by="creation asc",
	)
	for p in pages:
		if p.name == ctx.page_id:
			p["open_in_editor"] = True
		if p.name == ctx.target_page_id:
			p["working_page"] = True
	return json.dumps({"app": ctx.app_id, "pages": pages}, default=str)


def run_read_page(ctx, args: dict) -> str:
	from studio.ai.block_codec import BlockCodec

	page = resolve_page(ctx, args.get("page_name"))
	if isinstance(page, str):
		return page
	doc = frappe.get_doc("Studio Page", page)
	raw = doc.draft_blocks or doc.blocks or "[]"
	try:
		blocks = json.loads(raw)
	except json.JSONDecodeError:
		blocks = []
	root = blocks[0] if isinstance(blocks, list) and blocks else (blocks or {})
	structure = BlockCodec.to_json(BlockCodec.compress(root)) if root else "(empty page)"
	return json.dumps(
		{
			"name": doc.name,
			"title": doc.page_title,
			"route": doc.route,
			"structure": structure,
			"note": "Read-only reference. To edit this page, open_page first.",
		}
	)


def run_create_page(ctx, args: dict) -> str:
	title = (args.get("title") or "").strip()
	if not ctx.app_id:
		return "FAILED: this chat has no app in scope."
	if not title:
		return "FAILED: give the page a title."
	route = (args.get("route") or "").strip()
	if route and route_taken(ctx.app_id, route):
		return f"FAILED: route '{route}' is already used by another page in this app."
	doc = frappe.get_doc(
		{
			"doctype": "Studio Page",
			"studio_app": ctx.app_id,
			"page_title": title,
			**({"route": route} if route else {}),
		}
	).insert(ignore_permissions=True)
	ctx.note_page_event("created", doc)
	ctx.switch_target(doc.name)
	return (
		f"Created page '{doc.page_title}' (name: {doc.name}, route: {doc.route}) and made it the "
		"working page. Now build it with generate_page. The user sees a link to open it."
	)


def run_open_page(ctx, args: dict) -> str:
	page = resolve_page(ctx, args.get("page_name"))
	if isinstance(page, str):
		return page
	ctx.switch_target(page)
	where = "open in the editor" if page == ctx.page_id else "edited in the background"
	return f"Working page is now '{page}' ({where}). All block tools apply to it."


def run_set_page_meta(ctx, args: dict) -> str:
	page = resolve_page(ctx, args.get("page_name") or ctx.target_page_id)
	if isinstance(page, str):
		return page
	doc = frappe.get_doc("Studio Page", page)
	changed = []
	if title := (args.get("title") or "").strip():
		doc.page_title = title
		changed.append(f"title → '{title}'")
	if route := (args.get("route") or "").strip():
		if route_taken(ctx.app_id, route, exclude=doc.name):
			return f"FAILED: route '{route}' is already used by another page in this app."
		doc.route = route
		changed.append(f"route → '{route}'")
	if not changed:
		return "FAILED: nothing to change — pass title and/or route."
	doc.save(ignore_permissions=True)
	ctx.note_page_event("meta", doc)
	return f"Updated {doc.name}: {', '.join(changed)}."


def resolve_page(ctx, page_name: str | None) -> str:
	"""The page's docname, or a FAILED string. Accepts a route or title too —
	models often echo what the user said instead of the docname."""
	if not page_name:
		return "FAILED: pass page_name (see list_pages)."
	if frappe.db.exists("Studio Page", {"name": page_name, "studio_app": ctx.app_id}):
		return page_name
	for field in ("route", "page_title"):
		if found := frappe.db.get_value("Studio Page", {field: page_name, "studio_app": ctx.app_id}, "name"):
			return found
	return f"FAILED: no page '{page_name}' in this app. Call list_pages for real names."


def route_taken(app_id: str, route: str, exclude: str | None = None) -> bool:
	if not route.startswith("/"):
		route = f"/{route}"
	filters = {"studio_app": app_id, "route": route}
	if exclude:
		filters["name"] = ["!=", exclude]
	return bool(frappe.db.exists("Studio Page", filters))


TOOLS = [
	Tool(
		name="list_pages",
		side="server",
		description="List every page of this app: name, title, route, and which one is open in the editor / currently the working page.",
		parameters={"type": "object", "properties": {}},
		handler=run_list_pages,
	),
	Tool(
		name="read_page",
		side="server",
		description="Read another page of the app as reference: its title, route and full block structure. Use before building a sibling page so the app stays visually consistent.",
		parameters={
			"type": "object",
			"properties": {
				"page_name": {
					"type": "string",
					"description": "The page's name, route or title (list_pages gives names).",
				}
			},
			"required": ["page_name"],
		},
		handler=run_read_page,
	),
	Tool(
		name="create_page",
		side="server",
		description="Create a new page in this app and make it the working page. Follow with generate_page to build it. The user gets a link to open it in the editor.",
		parameters={
			"type": "object",
			"properties": {
				"title": {"type": "string", "description": "Human page title, e.g. 'Order History'."},
				"route": {
					"type": "string",
					"description": "Optional route like /orders. Derived from the title when omitted.",
				},
			},
			"required": ["title"],
		},
		handler=run_create_page,
	),
	Tool(
		name="open_page",
		side="server",
		description="Switch the working page. Every block tool then applies to it, whether or not the user has it open — edits are saved server-side.",
		parameters={
			"type": "object",
			"properties": {
				"page_name": {"type": "string", "description": "The page to work on (see list_pages)."}
			},
			"required": ["page_name"],
		},
		handler=run_open_page,
	),
	Tool(
		name="set_page_meta",
		side="server",
		description="Rename a page and/or change its route (collision-checked). Defaults to the working page when page_name is omitted.",
		parameters={
			"type": "object",
			"properties": {
				"page_name": {
					"type": "string",
					"description": "Page to update; defaults to the working page.",
				},
				"title": {"type": "string", "description": "New page title."},
				"route": {"type": "string", "description": "New route, e.g. /orders."},
			},
		},
		handler=run_set_page_meta,
	),
]
