"""Backend access: real records, new doctypes, and the app's Python package.

Reads are free (session-user permissions). Writes are proposals: create_doctype,
seed_sample_data and write_python_file end the turn with an Apply/Skip card and
mutate only when the user confirms (see studio.ai.agent.pending). Python file
access is standard-app only, jailed to the linked Frappe app's package, and
follows the same developer-mode + System Manager gate as the file editor.
"""

import json
import os

import frappe
from frappe import _

from studio.ai.agent.registry import Tool

MAX_FILE_BYTES = 200 * 1024
MAX_LISTED_FILES = 400
SKIP_DIRS = {"__pycache__", ".git", "node_modules", "public", "templates", "www"}


def run_query_records(ctx, args: dict) -> str:
	doctype = (args.get("doctype") or "").strip()
	if not doctype:
		return "FAILED: pass doctype."
	try:
		rows = frappe.get_list(
			doctype,
			filters=args.get("filters") or None,
			fields=args.get("fields") or ["name"],
			limit_page_length=min(int(args.get("limit") or 20), 100),
			order_by=args.get("order_by") or None,
		)
	except Exception as e:
		return f"FAILED: {type(e).__name__}: {e}"
	return json.dumps({"doctype": doctype, "count": len(rows), "records": rows}, default=str)


def run_get_document(ctx, args: dict) -> str:
	doctype = (args.get("doctype") or "").strip()
	name = (args.get("name") or "").strip()
	if not doctype or not name:
		return "FAILED: pass doctype and name."
	try:
		doc = frappe.get_doc(doctype, name)
		if not doc.has_permission():
			return f"FAILED: no permission to read {doctype} {name}."
	except frappe.DoesNotExistError:
		return f"FAILED: {doctype} '{name}' does not exist."
	except Exception as e:
		return f"FAILED: {type(e).__name__}: {e}"
	data = {k: v for k, v in doc.as_dict().items() if not k.startswith("_")}
	out = json.dumps(data, default=str)
	return out if len(out) < 8000 else out[:8000] + "… (truncated)"


def run_create_doctype(ctx, args: dict) -> None:
	from studio.ai.agent.pending import request_confirmation

	name = (args.get("name") or "").strip()
	fields = args.get("fields") or []
	summary = _("Create DocType '{0}' with {1} field(s)?").format(name, len(fields))
	request_confirmation(ctx, "create_doctype", summary, {"name": name, "fields": fields})


def run_seed_sample_data(ctx, args: dict) -> None:
	from studio.ai.agent.pending import request_confirmation

	doctype = (args.get("doctype") or "").strip()
	rows = args.get("rows") or []
	summary = _("Insert {0} sample record(s) into {1}?").format(len(rows), doctype)
	request_confirmation(ctx, "seed_sample_data", summary, {"doctype": doctype, "rows": rows})


# --- Python package files (standard apps only) --------------------------------


def validate_backend_access() -> None:
	if not frappe.conf.developer_mode:
		frappe.throw(_("Editing backend files is only allowed in developer mode."))
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("You do not have permission to edit backend files."), frappe.PermissionError)


def backend_root(frappe_app: str) -> str:
	"""The app's python package (apps/<app>/<app>) — the jail root."""
	return os.path.realpath(frappe.get_app_path(frappe_app))


def resolve_python_path(frappe_app: str | None, path: str | None) -> str:
	if not frappe_app or not path:
		frappe.throw(_("frappe_app and path are required"))
	if not path.endswith(".py"):
		frappe.throw(_("Only .py files can be edited here"))
	root = backend_root(frappe_app)
	target = os.path.realpath(os.path.join(root, path))
	if target != root and not target.startswith(root + os.sep):
		frappe.throw(_("Invalid path: {0}").format(path), frappe.PermissionError)
	return target


def linked_frappe_app(ctx) -> str | None:
	if not ctx.app_id:
		return None
	return frappe.db.get_value("Studio App", ctx.app_id, "frappe_app")


def run_list_backend_files(ctx, args: dict) -> str:
	try:
		validate_backend_access()
	except Exception as e:
		return f"FAILED: {e}"
	app = linked_frappe_app(ctx)
	if not app:
		return "FAILED: this Studio app is not linked to a Frappe app (export it first)."
	root = backend_root(app)
	found = []
	for dirpath, dirnames, filenames in os.walk(root):
		dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
		for name in sorted(filenames):
			if name.endswith(".py"):
				found.append(os.path.relpath(os.path.join(dirpath, name), root))
			if len(found) >= MAX_LISTED_FILES:
				break
		if len(found) >= MAX_LISTED_FILES:
			break
	return json.dumps({"frappe_app": app, "root": f"apps/{app}/{app}", "files": found})


def run_read_backend_file(ctx, args: dict) -> str:
	try:
		validate_backend_access()
	except Exception as e:
		return f"FAILED: {e}"
	app = linked_frappe_app(ctx)
	if not app:
		return "FAILED: this Studio app is not linked to a Frappe app."
	try:
		target = resolve_python_path(app, (args.get("path") or "").strip())
	except Exception as e:
		return f"FAILED: {e}"
	if not os.path.isfile(target):
		return f"FAILED: no file '{args.get('path')}' — list_backend_files shows what exists."
	if os.path.getsize(target) > MAX_FILE_BYTES:
		return "FAILED: file too large to read."
	with open(target, encoding="utf-8") as f:
		return f.read()


def run_write_python_file(ctx, args: dict) -> None:
	from studio.ai.agent.pending import request_confirmation

	app = linked_frappe_app(ctx)
	path = (args.get("path") or "").strip()
	summary = _("Write backend file {0} in app '{1}'? Review carefully — this is server code.").format(
		path, app
	)
	request_confirmation(
		ctx,
		"write_python_file",
		summary,
		{"frappe_app": app, "path": path, "content": args.get("content") or ""},
	)


SHARED_TOOLS = [
	Tool(
		name="query_records",
		side="server",
		handler=run_query_records,
		description=(
			"Query real records of any doctype with the current user's permissions: filters "
			"(Frappe list-filter dict), fields, order_by, limit (max 100). Ground the page in "
			"real data — never invent example records when real ones exist."
		),
		parameters={
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"filters": {"type": "object", "description": 'Frappe filters, e.g. {"status": "Open"}.'},
				"fields": {"type": "array", "items": {"type": "string"}},
				"order_by": {"type": "string", "description": "e.g. 'modified desc'."},
				"limit": {"type": "integer"},
			},
			"required": ["doctype"],
		},
	),
	Tool(
		name="get_document",
		side="server",
		handler=run_get_document,
		description="Read ONE full record (all fields) of a doctype by name, with permission checks.",
		parameters={
			"type": "object",
			"properties": {"doctype": {"type": "string"}, "name": {"type": "string"}},
			"required": ["doctype", "name"],
		},
	),
	Tool(
		name="create_doctype",
		side="terminal",
		handler=run_create_doctype,
		description=(
			"PROPOSE creating a new Custom DocType (name + fields). The user gets an "
			"Apply/Skip card — nothing is created until they apply. Use when the app needs "
			"to store data no existing doctype covers. Ends your turn."
		),
		parameters={
			"type": "object",
			"properties": {
				"name": {"type": "string", "description": "DocType name, e.g. 'Gym Member'."},
				"fields": {
					"type": "array",
					"items": {
						"type": "object",
						"properties": {
							"fieldname": {"type": "string"},
							"label": {"type": "string"},
							"fieldtype": {"type": "string", "description": "Data, Int, Date, Select, Link…"},
							"options": {"type": "string", "description": "Select options / Link target."},
						},
						"required": ["fieldname"],
					},
				},
			},
			"required": ["name", "fields"],
		},
	),
	Tool(
		name="seed_sample_data",
		side="terminal",
		handler=run_seed_sample_data,
		description=(
			"PROPOSE inserting sample records into a doctype so the page has something real "
			"to show. Apply/Skip card; nothing inserted until the user applies. Ends your turn."
		),
		parameters={
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"rows": {"type": "array", "items": {"type": "object"}},
			},
			"required": ["doctype", "rows"],
		},
	),
]

FILE_TOOLS = [
	Tool(
		name="list_backend_files",
		side="server",
		handler=run_list_backend_files,
		description=(
			"List the linked Frappe app's Python files (controllers, APIs). Use to find "
			"where whitelisted methods live before reading or proposing one."
		),
		parameters={"type": "object", "properties": {}},
	),
	Tool(
		name="read_backend_file",
		side="server",
		handler=run_read_backend_file,
		description=(
			"Read one Python file from the linked Frappe app's package — understand existing "
			"controllers and whitelisted methods before wiring the page to them."
		),
		parameters={
			"type": "object",
			"properties": {
				"path": {"type": "string", "description": "Relative to the app package, e.g. 'api.py'."}
			},
			"required": ["path"],
		},
	),
	Tool(
		name="write_python_file",
		side="terminal",
		handler=run_write_python_file,
		description=(
			"PROPOSE writing a backend Python file (e.g. a new whitelisted method the page "
			"calls). The user reviews the full content in an Apply/Skip card — nothing is "
			"written until they apply. Always read the existing file first and send the "
			"COMPLETE new file content. Ends your turn."
		),
		parameters={
			"type": "object",
			"properties": {
				"path": {"type": "string", "description": "Relative to the app package, e.g. 'api.py'."},
				"content": {"type": "string", "description": "The complete file content."},
			},
			"required": ["path", "content"],
		},
	),
]
