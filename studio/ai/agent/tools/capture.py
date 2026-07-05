"""Canvas capture tool — lets the agent SEE the rendered page mid-turn.

The worker can't screenshot the canvas (it lives in the user's browser), so this is a
round-trip: the handler emits a `capture_request` realtime event, the editor captures the
canvas (see frontend `captureCanvas.ts`) and posts it back via `studio.ai.api.submit_capture`,
which stashes it in the cache where the handler is polling. The capture — plus the design the
user attached earlier in the session, when there is one — is queued on `ctx.pending_images`;
the loop attaches those to the next user message so the model can compare and refine.
"""

import json
import time

import frappe

from studio.ai.agent.registry import Tool
from studio.ai.models import ModelRegistry
from studio.ai.session import AISession

CAPTURE_TIMEOUT_SECONDS = 20.0
POLL_INTERVAL_SECONDS = 0.5


def capture_cache_key(session_id: str) -> str:
	return f"studio_ai_capture:{session_id}"


def run_capture_page_render(ctx, args: dict) -> str:
	if not ModelRegistry.is_vision_capable(ctx.model):
		return (
			"FAILED: the selected model cannot read images. Proceed from the block tree, or tell "
			"the user to switch to a vision-capable model."
		)
	ctx.emit("capture_request", session_id=ctx.session_id)
	render = _await_capture(ctx)
	if not render:
		return (
			"FAILED: the editor did not return a capture in time (the tab may be closed or busy). "
			"Proceed from the block tree instead."
		)

	images = []
	if design := _latest_attached_design(ctx.session_id):
		images.append({"label": "TARGET DESIGN", "url": design})
	images.append({"label": "CURRENT RENDER", "url": render})
	ctx.pending_images.extend(images)
	labels = " and ".join(image["label"] for image in images)
	return (
		f"Captured — {labels} attached to the next message. Compare them, list the concrete "
		"discrepancies, then fix each with targeted block edits."
	)


def _await_capture(ctx) -> str | None:
	"""Poll the cache for the editor's answer to the capture_request event, honoring cancel."""
	from studio.ai.agent.loop import CancelledError

	key = capture_cache_key(ctx.session_id)
	waited = 0.0
	while waited < CAPTURE_TIMEOUT_SECONDS:
		if data := frappe.cache.get_value(key):
			frappe.cache.delete_value(key)
			return data
		if ctx.is_cancelled():
			raise CancelledError
		time.sleep(POLL_INTERVAL_SECONDS)
		waited += POLL_INTERVAL_SECONDS
	return None


def _latest_attached_design(session_id: str) -> str | None:
	"""The most recent design the user attached in this session (stored on the user message
	as attachedImageUrl), so a refine can always compare against it."""
	if not session_id:
		return None
	rows = frappe.db.get_all(
		AISession.MESSAGE_DOCTYPE,
		filters={"session": session_id, "role": "user"},
		fields=["metadata_json"],
		order_by="creation desc",
		limit_page_length=20,
	)
	for row in rows:
		try:
			metadata = json.loads(row.metadata_json or "{}") or {}
		except (json.JSONDecodeError, TypeError):
			continue
		if url := metadata.get("attachedImageUrl"):
			return url
	return None


capture_page_render = Tool(
	name="capture_page_render",
	side="server",
	handler=run_capture_page_render,
	description=(
		"Screenshot the CURRENT rendered page from the editor so you can SEE it. The capture — "
		"plus the TARGET DESIGN the user attached earlier, when there is one — arrives as images "
		"on the next message. Call this when the user asks to match an attached design, or reports "
		"a visual/layout problem the block tree alone can't settle (overlap, misalignment, 'looks "
		"off'). Do NOT call it for changes you can already make from the block tree (rename text, "
		"set a color the user named). Takes a few seconds."
	),
	parameters={"type": "object", "properties": {}},
)

TOOLS = [capture_page_render]
