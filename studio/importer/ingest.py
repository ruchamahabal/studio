# Ingests a Studio import manifest (produced by frontend/src/importer) into the
# Studio database: creates a Studio App and its Studio Pages with blocks,
# resources, variables, watchers and client scripts.
#
# Usage:
#   bench --site <site> execute studio.importer.ingest.ingest_manifest \
#       --kwargs "{'manifest_path': '/tmp/studio-manifest.json'}"

import json

import frappe


@frappe.whitelist()
def ingest_manifest(manifest_path: str, reset: bool = True) -> dict:
	with open(manifest_path) as f:
		manifest = json.load(f)

	app_name = ensure_app(manifest)
	if reset:
		delete_existing_pages(app_name)

	created = []
	for page in manifest["pages"]:
		created.append(create_page(app_name, manifest["frappe_app"], page))

	frappe.db.commit()
	return {
		"app": app_name,
		"pages": created,
		"custom_components": [c["component_name"] for c in manifest.get("custom_components", [])],
	}


@frappe.whitelist()
def inspect_app(app_name: str) -> dict:
	"""Summarise an imported Studio App for verification."""
	from studio.api import get_custom_vue_components

	pages = []
	for page_name in frappe.get_all("Studio Page", filters={"studio_app": app_name}, pluck="name"):
		page = frappe.get_doc("Studio Page", page_name)
		blocks = json.loads(page.blocks or "[]")
		pages.append(
			{
				"name": page.name,
				"route": page.route,
				"title": page.page_title,
				"block_count": _count_blocks(blocks),
				"variables": [v.variable_name for v in page.variables],
				"watchers": len(page.watchers),
				"resources": [r.resource_name for r in page.resources],
				"client_scripts": [r.studio_script for r in page.client_scripts],
			}
		)

	frappe_app = frappe.db.get_value("Studio App", app_name, "frappe_app")
	discovered = [c["component_name"] for c in get_custom_vue_components(frappe_app)] if frappe_app else []
	return {
		"app": app_name,
		"frappe_app": frappe_app,
		"pages": pages,
		"discovered_custom_components": discovered,
	}


def _count_blocks(blocks: list) -> int:
	total = 0
	for block in blocks:
		total += 1
		total += _count_blocks(block.get("children", []))
		for slot in (block.get("componentSlots") or {}).values():
			content = slot.get("slotContent")
			if isinstance(content, list):
				total += _count_blocks(content)
	return total


def ensure_app(manifest: dict) -> str:
	app_name = manifest["app_name"]
	if frappe.db.exists("Studio App", app_name):
		return app_name

	doc = frappe.new_doc("Studio App")
	doc.app_name = app_name
	doc.app_title = manifest.get("app_title") or app_name
	doc.frappe_app = manifest.get("frappe_app")
	doc.route = f"/{app_name}"
	doc.is_standard = 0
	doc.insert(ignore_permissions=True)
	return doc.name


def delete_existing_pages(app_name: str) -> None:
	for page_name in frappe.get_all("Studio Page", filters={"studio_app": app_name}, pluck="name"):
		page = frappe.get_doc("Studio Page", page_name)
		script_names = [row.studio_script for row in page.client_scripts if row.studio_script]
		frappe.delete_doc("Studio Page", page_name, ignore_permissions=True, force=True)
		for script_name in script_names:
			frappe.delete_doc(
				"Studio Client Script", script_name, ignore_permissions=True, force=True, ignore_missing=True
			)


def create_page(app_name: str, frappe_app: str, page: dict) -> str:
	doc = frappe.new_doc("Studio Page")
	doc.studio_app = app_name
	doc.frappe_app = frappe_app
	doc.page_title = page["page_title"]
	doc.route = page["route"]
	doc.is_standard = 0
	doc.blocks = frappe.as_json(page["blocks"], indent=None)

	for variable in page.get("variables", []):
		doc.append("variables", variable)

	for resource in page.get("resources", []):
		doc.append("resources", normalize_resource(resource))

	for watcher in page.get("watchers", []):
		doc.append("watchers", watcher)

	for script in page.get("client_scripts", []):
		script_name = create_client_script(app_name, page["page_title"], script)
		doc.append("client_scripts", {"studio_script": script_name})

	doc.insert(ignore_permissions=True)
	return doc.name


def normalize_resource(resource: dict) -> dict:
	# JSON child fields must be strings; provide safe defaults for empty ones
	resource = dict(resource)
	for field, default in (
		("fields", "[]"),
		("filters", "{}"),
		("params", "{}"),
		("whitelisted_methods", "[]"),
	):
		if not resource.get(field):
			resource[field] = default
	return resource


def create_client_script(app_name: str, page_title: str, script: dict) -> str:
	name = f"{app_name}-{frappe.scrub(page_title)}-{frappe.scrub(script['name_hint'])}"
	if frappe.db.exists("Studio Client Script", name):
		frappe.delete_doc("Studio Client Script", name, ignore_permissions=True, force=True)

	doc = frappe.get_doc(
		{
			"doctype": "Studio Client Script",
			"name": name,
			"script": script["script"],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name
