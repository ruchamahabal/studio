"""Confirm-gating for sensitive agent actions.

A sensitive tool NEVER mutates directly. Its handler validates the proposal,
then calls `request_confirmation`, which persists a pending-action message and
emits a clarify event carrying the card, then ends the turn (the tool is
side="terminal"). The panel renders an Approve/Skip card — persisted, so it
survives an editor reload; on Approve the `confirm_pending_action` endpoint
(ai/api.py) loads the stored payload and runs `apply_pending_action` in the
APPROVING USER's request context. The model can only propose.

Action kinds are an explicit whitelist dispatching to ctx-free apply functions:
an unknown or forged kind can never run, and apply re-validates the stored
payload from scratch — it sat in the DB while the disk may have moved on.
"""

import frappe
from frappe import _

from studio.ai.agent import backend_files
from studio.ai.session import AISession
from studio.utils import ensure_developer_file_access

# Kinds the confirm card understands. Explicit so an unknown kind can never be applied.
KINDS = {"write_backend_file"}


def request_confirmation(ctx, kind: str, summary: str, payload: dict, card: dict) -> None:
	"""Persist + emit a pending sensitive action, then end the turn without mutating.
	`payload` is what apply needs; `card` is what the approval card shows (path, diff,
	warnings) — kept top-level in metadata so the panel reads one shape."""
	metadata = {"status": "pending_action", "kind": kind, "payload": payload, **card}
	message_id = AISession.try_append_message(
		ctx.session_id,
		"assistant",
		summary,
		message_type="clarification",
		task_type="agent",
		metadata=metadata,
	)
	# Commit BEFORE emitting: the event triggers a session reload on the client,
	# which must find this message (and its pending status) already in the DB.
	frappe.db.commit()
	ctx.emit(
		"clarify",
		question=summary,
		options=[],
		pending_action={"kind": kind, "message_id": message_id, **card},
	)


def apply_pending_action(kind: str, payload: dict) -> str:
	"""Run the real mutation for an approved action. Called ONLY from the confirm
	endpoint (user-triggered). Returns a short human summary of what happened."""
	if kind not in KINDS:
		frappe.throw(_("Unknown pending action: {0}").format(kind))
	return {"write_backend_file": apply_write_backend_file}[kind](payload or {})


def apply_write_backend_file(payload: dict) -> str:
	frappe_app = (payload.get("frappe_app") or "").strip()
	file_path = (payload.get("file_path") or "").strip("/")
	content = payload.get("content")
	if not frappe_app or not file_path or not isinstance(content, str):
		frappe.throw(_("The stored proposal is incomplete."))

	# Re-run EVERY propose-time check: gate, app ownership, jail, protected files,
	# lint — then refuse if the file drifted on disk since the card was shown.
	ensure_developer_file_access()
	if not frappe.db.exists("Studio App", {"frappe_app": frappe_app, "is_standard": 1}):
		frappe.throw(_("{0} is not an exported Studio app.").format(frappe_app))
	if reason := backend_files.app_error(frappe_app) or backend_files.writable_error(file_path):
		frappe.throw(_(reason))
	error, _warnings, whitelisted = backend_files.lint(frappe_app, file_path, content)
	if error:
		frappe.throw(_("The proposed code no longer validates: {0}").format(error))

	current = backend_files.read_current(frappe_app, file_path)
	if current != content:
		# Idempotency: current == content means a previous approve already landed the
		# file but the request died before committing (writing a .py restarts the dev
		# server, which can kill the very request that wrote it) — re-approving must
		# succeed, not trip the drift check against our own write.
		if backend_files.file_hash(current or "") != payload.get("prior_hash"):
			frappe.throw(
				_("{0} changed on disk since this was proposed. Ask the agent to re-propose.").format(
					file_path
				)
			)
		backend_files.write(frappe_app, file_path, content)
	outcome = _("Wrote {0}.").format(file_path)
	if whitelisted:
		module = backend_files.dotted_path(frappe_app, file_path)
		calls = ", ".join(f"call('{module}.{name}')" for name in whitelisted)
		outcome += _(" Pages can call: {0}.").format(calls)
	return outcome + _(
		" The change is live for web requests (the dev server reloads); background workers pick it up on restart."
	)
