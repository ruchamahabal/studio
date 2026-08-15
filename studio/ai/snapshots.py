"""Pre-turn page snapshots for reverting an AI turn.

State is captured synchronously at the start of the turn (before the loop or
any streaming touches the page) and a Studio AI Snapshot doc is created ONLY
when the turn actually mutates something — no-op, clarify and plan turns leave
nothing behind. Revert restores the DB-backed page state (canvas blocks, page
script, data sources) and truncates the conversation; files a standard page's
turn wrote on disk are out of scope and stay.
"""

import json

import frappe

logger = frappe.logger("studio.ai.snapshots")

# How many AI snapshots to keep per page.
KEEP_AI_SNAPSHOTS = 10

# The child-table bookkeeping columns that must not ride along into a restore.
CHILD_META_FIELDS = {
	"name",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"docstatus",
	"idx",
	"parent",
	"parentfield",
	"parenttype",
}


def capture_page_state(page_id: str | None) -> dict | None:
	"""Read the page's current blocks + script + data sources into a plain dict
	(no doc created), so ONE revert restores everything a turn can touch."""
	if not page_id or not frappe.db.exists("Studio Page", page_id):
		return None
	doc = frappe.get_doc("Studio Page", page_id)
	field = "draft_blocks" if doc.get("draft_blocks") else "blocks"
	state = {
		"blocks_field": field,
		"blocks": doc.get(field),
		"script": doc.get("script"),
		"resources": [
			{k: v for k, v in row.as_dict().items() if k not in CHILD_META_FIELDS}
			for row in (doc.get("resources") or [])
		],
	}
	return state


def save_revert_snapshot(
	page_id: str | None, state: dict | None, session_id: str | None = None
) -> str | None:
	"""Persist a captured pre-turn `state` and prune old ones. Returns the snapshot
	name, or None if there was nothing to save. A snapshot failure never blocks the
	turn — the change is already applied; revert just won't be offered."""
	if not page_id or not state:
		return None
	try:
		doc = frappe.get_doc(
			{
				"doctype": "Studio AI Snapshot",
				"page": page_id,
				"session": session_id or "",
				"reason": "Before AI edit",
				"state_json": json.dumps(state, separators=(",", ":"), default=str),
			}
		).insert(ignore_permissions=True)
		prune_snapshots(page_id)
		return doc.name
	except Exception:
		logger.warning("Failed to save AI revert snapshot", exc_info=True)
		return None


def restore_snapshot(snapshot_name: str) -> str:
	"""Put the page back the way the snapshot recorded it. Returns the page id."""
	snap = frappe.get_doc("Studio AI Snapshot", snapshot_name)
	state = json.loads(snap.state_json or "{}")
	page = frappe.get_doc("Studio Page", snap.page)
	page.set(state.get("blocks_field") or "draft_blocks", state.get("blocks"))
	page.set("script", state.get("script"))
	page.set("resources", state.get("resources") or [])
	page.save(ignore_permissions=True)
	return snap.page


def prune_snapshots(page_id: str) -> None:
	stale = frappe.get_all(
		"Studio AI Snapshot",
		filters={"page": page_id},
		order_by="creation desc",
		pluck="name",
	)[KEEP_AI_SNAPSHOTS:]
	for name in stale:
		frappe.delete_doc("Studio AI Snapshot", name, ignore_permissions=True, delete_permanently=True)
