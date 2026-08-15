"""Confirm-gating for sensitive agent actions.

A sensitive tool NEVER mutates directly. It calls `request_confirmation`, which
persists a pending-action message and emits a clarify event carrying the payload,
then ends the turn (the tool is `side="terminal"`). The frontend renders an
Apply/Skip card; Apply calls the `confirm_pending_action` endpoint, which loads
the stored payload and runs `apply_pending_action`. So every privileged write
(new doctype, sample data, backend Python) is user-triggered — the model can
only *propose*.
"""

import os

import frappe
from frappe import _

from studio.ai.session import AISession

# Sensitive action kinds the confirm card understands. Kept explicit so an
# unknown kind can never be applied.
KINDS = {"create_doctype", "seed_sample_data", "write_python_file"}


def request_confirmation(ctx, kind: str, summary: str, payload: dict) -> None:
	"""Persist + emit a pending sensitive action, then end the turn without mutating."""
	metadata = {"status": "pending_action", "kind": kind, "payload": payload}
	# Without the timeline, everything the turn did before proposing is invisible
	# on reload.
	if timeline := ctx.timeline():
		metadata["steps"] = timeline
	message_id = AISession.try_append_message(
		ctx.session_id,
		"assistant",
		summary,
		message_type="clarification",
		task_type="agent",
		metadata=metadata,
	)
	frappe.db.commit()  # the card must be durable before the event announces it
	ctx.emit(
		"clarify",
		question=summary,
		options=["Apply", "Skip"],
		pending_action={"kind": kind, "payload": payload},
		message_id=message_id,
	)


def apply_pending_action(kind: str, payload: dict) -> str:
	"""Run the real mutation for a confirmed action. Called ONLY from the confirm
	endpoint (user-triggered). Returns a short human summary of what happened."""
	if kind not in KINDS:
		frappe.throw(_("Unknown pending action: {0}").format(kind))
	payload = payload or {}
	return {
		"create_doctype": apply_create_doctype,
		"seed_sample_data": apply_seed_sample_data,
		"write_python_file": apply_write_python_file,
	}[kind](payload)


def apply_create_doctype(payload: dict) -> str:
	"""Create a Custom DocType (custom=1, created at runtime — no code files or
	migration). Read for all logged-in users, so app pages can query it."""
	name = (payload.get("name") or "").strip()
	if not name:
		frappe.throw(_("Doctype name is required"))
	if frappe.db.exists("DocType", name):
		return _("DocType {0} already exists").format(name)

	fields = []
	for f in payload.get("fields") or []:
		fieldname = (f.get("fieldname") or "").strip()
		if not fieldname:
			continue
		fields.append(
			{
				"fieldname": fieldname,
				"label": f.get("label") or fieldname.replace("_", " ").title(),
				"fieldtype": f.get("fieldtype") or "Data",
				"options": f.get("options"),
				"in_list_view": 1,
			}
		)
	if not fields:
		frappe.throw(_("At least one field is required"))

	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": name,
			"module": "Studio",
			"custom": 1,
			"naming_rule": "Random",
			"fields": fields,
			"permissions": [
				{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
				{"role": "All", "read": 1, "write": 1, "create": 1},
			],
		}
	).insert(ignore_permissions=True)
	return _("Created DocType {0} with {1} field(s)").format(name, len(fields))


def apply_seed_sample_data(payload: dict) -> str:
	doctype = (payload.get("doctype") or "").strip()
	rows = payload.get("rows") or []
	if not doctype or not frappe.db.exists("DocType", doctype):
		frappe.throw(_("DocType {0} does not exist").format(doctype))
	created = 0
	for row in rows:
		if not isinstance(row, dict):
			continue
		frappe.get_doc({"doctype": doctype, **row}).insert(ignore_permissions=True)
		created += 1
	return _("Seeded {0} sample record(s) into {1}").format(created, doctype)


def apply_write_python_file(payload: dict) -> str:
	"""Write a backend Python file inside the app-package jail. Reaches here only
	after the user clicked Apply; the same developer-mode + System Manager gate as
	the frontend file tools applies."""
	from studio.ai.agent.tools.backend import resolve_python_path, validate_backend_access

	validate_backend_access()
	target = resolve_python_path(payload.get("frappe_app"), payload.get("path"))
	content = payload.get("content") or ""
	os.makedirs(os.path.dirname(target), exist_ok=True)
	with open(target, "w", encoding="utf-8") as f:
		f.write(content)
	return _("Wrote {0}").format(payload.get("path"))
