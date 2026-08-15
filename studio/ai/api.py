"""Whitelisted endpoints for the Studio AI agent.

A single conversational entry point — `run` — drives the unified agent loop for
one user turn (generation and editing alike). `cancel` requests that a running turn
abort at its next stream chunk; `get_ai_session`/`clear_ai_session` read and reset the
per-page chat history.
"""

import json
import logging

import frappe
from frappe import _

from studio.ai import llm, locks
from studio.ai.agent.loop import run_agent_job
from studio.ai.block_codec import BlockCodec
from studio.ai.models import ModelRegistry
from studio.ai.session import AISession
from studio.utils import has_page_write_perm

logger = frappe.logger("studio.ai.api")
logger.setLevel(logging.INFO)


def resolve_api_key(model: str | None = None) -> str:
	"""The key to call `model` with: its provider's own key when it has one (a
	local or self-hosted gateway needs no OpenRouter account at all), otherwise
	the shared key from Studio Settings. OAuth providers (codex) carry their own
	credential and need no key here."""
	if model:
		from studio.ai.llm import codex_route, provider_api_key

		if codex_route(model):
			return ""
		info = ModelRegistry.find(model)
		if info and (key := provider_api_key(info)):
			return key
	api_key = llm.get_api_key()
	if not api_key:
		frappe.throw(_("Please configure an API key in Studio Settings, or one on the model's provider"))
	return api_key


def resolve_app(app_id: str | None, page_id: str | None) -> str:
	"""The app this turn works on. A page-scoped caller (the page editor) only
	knows its page; the app is derived from it."""
	if app_id:
		return app_id
	if page_id:
		if app := frappe.db.get_value("Studio Page", page_id, "studio_app"):
			return app
	frappe.throw(_("Could not resolve the Studio App for this chat"))


@frappe.whitelist()
@has_page_write_perm()
def run(
	prompt: str,
	page_context: str = "",
	page_id: str | None = None,
	app_id: str | None = None,
	session_id: str | None = None,
	model: str | None = None,
	selected_block_ids: list | str | None = None,
	image_data: str | None = None,
):
	"""Single entry point: run the agent for one user turn. Sessions are app-scoped;
	`page_id` is the page open in the editor (focus + live canvas context), absent
	for the app-level chat. `image_data` is an optional base64 image data URL
	(a screenshot/design) the model should reproduce as a layout."""
	logger.info(f"run: app_id={app_id}, page_id={page_id}, session={session_id}, model={model}")

	if page_context:
		try:
			json.loads(page_context)
		except (json.JSONDecodeError, TypeError):
			frappe.throw(_("Invalid page context JSON"))

	app_id = resolve_app(app_id, page_id)
	resolved_model = ModelRegistry.get_default(model)
	api_key = resolve_api_key(resolved_model)

	image_url = BlockCodec.validate_image_data(image_data) if image_data else None

	if session_id:
		session = AISession.get(session_id)
	else:
		session = AISession.get_or_create(app_id, resolved_model, page_id=page_id)
	if locks.held(locks.session_key(session.name)):
		frappe.local.response.http_status_code = 429
		return {"status": "busy", "message": _("Another AI request is still processing. Please wait.")}

	# Store the image on the user message so the chat thread can show a thumbnail on reload.
	msg_meta = {"attachedImageUrl": image_url} if image_url else None
	session.append_message("user", prompt, message_type="chat", task_type="agent", metadata=msg_meta)

	# Background queue (not now=True): a streaming turn can run for tens of seconds, and
	# now=True would hold this web worker open for the whole stream — exhausting the worker
	# pool under concurrency. Realtime events flow over Redis pub/sub regardless of process.
	frappe.enqueue(
		run_agent_job,
		queue="long",
		timeout=600,
		prompt=prompt,
		page_context_json=page_context,
		model=resolved_model,
		api_key=api_key,
		user=frappe.session.user,
		app_id=app_id,
		page_id=page_id,
		session_id=session.name,
		selected_block_ids=_parse_block_ids(selected_block_ids),
		image_url=image_url,
	)
	frappe.local.response.http_status_code = 202
	return {"status": "accepted", "session_id": session.name}


@frappe.whitelist()
@has_page_write_perm()
def cancel(session_id: str):
	"""Request that the currently-running turn for this session abort at its next stream
	chunk. The loop closes the LLM stream — Anthropic / OpenRouter stop billing for further
	tokens once the connection drops. When no run is alive (worker died, lock expired),
	say so with an error event so a spinning client stops waiting for a ghost."""
	if not session_id:
		return {"status": "ok"}
	if not locks.held(locks.session_key(session_id)):
		session = AISession.get(session_id)
		event = f"ai_chat_error_{session.page}" if session.page else "ai_chat_error"
		frappe.publish_realtime(
			event,
			{"page_id": session.page, "message": _("The AI run is no longer active.")},
			user=frappe.session.user,
		)
		return {"status": "not_running"}
	frappe.cache.set_value(f"studio_ai_cancel:{session_id}", "1", expires_in_sec=300)
	return {"status": "ok"}


@frappe.whitelist()
@has_page_write_perm()
def get_ai_session(
	page_id: str | None = None,
	model: str | None = None,
	app_id: str | None = None,
	session_id: str | None = None,
) -> dict:
	if session_id:
		session = AISession.get(session_id)
	else:
		app_id = resolve_app(app_id, page_id)
		session = AISession.get_or_create(app_id, model, page_id=page_id)
	# Return the session id so the client can cancel a turn it didn't start itself — e.g. when a
	# page is opened while a previously-launched turn is still running in the background.
	return {
		"session_id": session.name,
		"app": session.app or "",
		"title": session._doc.title or "",
		"messages": session.get_messages(),
		"selected_model": session.selected_model or "",
		"is_running": locks.held(locks.session_key(session.name)),
	}


@frappe.whitelist()
@has_page_write_perm()
def list_ai_sessions(app_id: str) -> list[dict]:
	return AISession.list_for_app(app_id)


@frappe.whitelist()
@has_page_write_perm()
def new_ai_session(app_id: str, model: str | None = None, page_id: str | None = None) -> dict:
	session = AISession.create(app_id, model=model, page_id=page_id)
	return {"session_id": session.name, "app": app_id, "messages": [], "selected_model": model or ""}


@frappe.whitelist()
@has_page_write_perm()
def revert_to_message(session_id: str, message_id: str) -> dict:
	"""Undo an AI turn: restore the page from the turn's pre-edit snapshot and
	rewind the conversation to before that turn. Rejected while a turn is running
	(the worker would immediately overwrite the restored state)."""
	from studio.ai import snapshots

	if locks.held(locks.session_key(session_id)):
		frappe.throw(_("Wait for the running AI request to finish before reverting."))
	session = AISession.get(session_id)
	metadata_json = frappe.db.get_value(
		"Studio AI Message", {"name": message_id, "session": session_id}, "metadata_json"
	)
	meta = json.loads(metadata_json or "{}")
	if not meta.get("revertSnapshot"):
		frappe.throw(_("This turn has nothing to revert to"))
	page_id = snapshots.restore_snapshot(meta["revertSnapshot"])
	session.truncate_from_turn(message_id)
	frappe.db.commit()
	frappe.publish_realtime(f"ai_chat_reload_{page_id}", {"page_id": page_id}, user=frappe.session.user)
	return {"messages": session.get_messages()}


@frappe.whitelist()
@has_page_write_perm()
def clear_ai_session(
	page_id: str | None = None, app_id: str | None = None, session_id: str | None = None
) -> dict:
	if session_id:
		session = AISession.get(session_id)
	else:
		session = AISession.get_or_create(resolve_app(app_id, page_id))
	session.clear()
	return {"status": "ok"}


@frappe.whitelist()
@has_page_write_perm()
def report_page_error(page_id: str, message: str, source: str = "", stack: str = "") -> dict:
	"""The renderer (editor canvas / dev preview) reports uncaught errors here so
	the agent can read them via get_page_errors and fix its own breakage."""
	from studio.ai.agent.tools.errors import record_error

	if page_id and frappe.db.exists("Studio Page", page_id):
		record_error(page_id, message, source, stack)
	return {"status": "ok"}


def _parse_block_ids(selected_block_ids: list | str | None) -> list[str]:
	if isinstance(selected_block_ids, str):
		try:
			selected_block_ids = json.loads(selected_block_ids)
		except (json.JSONDecodeError, TypeError):
			return []
	return selected_block_ids if isinstance(selected_block_ids, list) else []
