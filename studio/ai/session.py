import json

import frappe
from frappe import _


class AISession:
	DOCTYPE = "Studio AI Session"
	MESSAGE_DOCTYPE = "Studio AI Message"
	CONTEXT_WINDOW = 10  # how many prior turns to feed back to the model

	def __init__(self, doc):
		self._doc = doc

	# --- factories --------------------------------------------------------

	@classmethod
	def get_or_create(
		cls, app_id: str, model: str | None = None, user: str | None = None, page_id: str | None = None
	):
		"""The user's most recent Active session for this app, or a fresh one.
		Sessions are app-scoped; `page_id` only updates the focus context."""
		user = user or frappe.session.user
		session_name = frappe.db.get_value(
			cls.DOCTYPE,
			{"app": app_id, "user": user, "status": ("!=", "Archived")},
			"name",
			order_by="last_interaction_on desc",
		)
		if session_name:
			doc = frappe.get_doc(cls.DOCTYPE, str(session_name))
			updates = {}
			if model and not doc.selected_model:
				updates["selected_model"] = model
			if page_id and doc.page != page_id:
				updates["page"] = page_id
			if updates:
				doc.update(updates)
				doc.save(ignore_permissions=True)
			return cls(doc)
		return cls.create(app_id, model=model, user=user, page_id=page_id)

	@classmethod
	def create(
		cls, app_id: str, model: str | None = None, user: str | None = None, page_id: str | None = None
	):
		doc = frappe.get_doc(
			{
				"doctype": cls.DOCTYPE,
				"app": app_id,
				"page": page_id or "",
				"user": user or frappe.session.user,
				"status": "Active",
				"selected_model": model or "",
				"last_interaction_on": frappe.utils.now_datetime(),
			}
		)
		doc.insert(ignore_permissions=True)
		return cls(doc)

	@classmethod
	def get(cls, session_id: str, user: str | None = None):
		user = user or frappe.session.user
		if not frappe.db.exists(cls.DOCTYPE, session_id):
			frappe.throw(_("AI session not found"))
		doc = frappe.get_doc(cls.DOCTYPE, session_id)
		if doc.user != user:
			frappe.throw(_("You do not have access to this AI session"))
		return cls(doc)

	@classmethod
	def list_for_app(cls, app_id: str, user: str | None = None) -> list[dict]:
		return frappe.get_all(
			cls.DOCTYPE,
			filters={"app": app_id, "user": user or frappe.session.user},
			fields=["name", "title", "status", "page", "last_interaction_on"],
			order_by="last_interaction_on desc",
			limit_page_length=50,
		)

	@classmethod
	def try_append_message(cls, session_id: str | None, role: str, content: str, **kwargs) -> str | None:
		if session_id and frappe.db.exists(cls.DOCTYPE, session_id):
			return cls(frappe.get_doc(cls.DOCTYPE, session_id)).append_message(role, content, **kwargs)
		return None

	@classmethod
	def attach_metadata_to_last_assistant(cls, session_id: str | None, extra_metadata: dict):
		if session_id and frappe.db.exists(cls.DOCTYPE, session_id):
			cls(frappe.get_doc(cls.DOCTYPE, session_id)).update_last_assistant_metadata(extra_metadata)

	@classmethod
	def build_context_messages_from_id(cls, session_id: str | None) -> list[dict]:
		if not session_id or not frappe.db.exists(cls.DOCTYPE, session_id):
			return []
		return cls(frappe.get_doc(cls.DOCTYPE, session_id)).build_context_messages()

	# --- properties -------------------------------------------------------

	@property
	def name(self):
		return self._doc.name

	@property
	def app(self):
		return self._doc.app

	@property
	def page(self):
		return self._doc.page

	@property
	def selected_model(self):
		return self._doc.selected_model

	@property
	def last_task_type(self):
		return self._doc.last_task_type

	# --- message read -----------------------------------------------------

	@staticmethod
	def _row_to_message(row: dict) -> dict:
		"""Reshape a Studio AI Message DB row into the ChatMessage dict shape the
		frontend renders."""
		try:
			metadata = json.loads(row.get("metadata_json") or "{}") or {}
		except (json.JSONDecodeError, TypeError):
			metadata = {}
		# `status` lives in its own column for queryability; surface it in the
		# returned metadata dict so callers see the same shape as before.
		if row.get("status"):
			metadata["status"] = row["status"]
		return {
			"id": row.get("name"),
			"role": row.get("role"),
			"content": row.get("content") or "",
			"message_type": row.get("message_type"),
			"task_type": row.get("task_type") or None,
			"component_id": row.get("component_id") or None,
			"created_at": str(row.get("creation")) if row.get("creation") else None,
			"metadata": metadata,
		}

	_FIELDS = (
		"name",
		"role",
		"content",
		"message_type",
		"task_type",
		"component_id",
		"status",
		"metadata_json",
		"creation",
	)

	def get_messages(self) -> list[dict]:
		"""Return ALL messages for this session in chronological order, shaped for
		the frontend's ChatMessage interface."""
		rows = frappe.db.get_all(
			self.MESSAGE_DOCTYPE,
			filters={"session": self._doc.name},
			fields=list(self._FIELDS),
			order_by="creation asc",
			limit_page_length=0,
		)
		return [self._row_to_message(r) for r in rows]

	def build_context_messages(self) -> list[dict]:
		"""Return the last N prior turns as proper role-tagged messages.

		Excludes the current-turn user message (the caller appends a fresh one),
		and filters out transient status/error/cancelled chatter."""
		# Fetch one extra (the current user message) and drop it.
		rows = frappe.db.get_all(
			self.MESSAGE_DOCTYPE,
			filters={"session": self._doc.name},
			fields=["role", "content", "message_type", "status", "metadata_json"],
			order_by="creation desc",
			limit_page_length=self.CONTEXT_WINDOW + 1,
		)
		# Skip the most recent row (current user msg) and reverse to chrono order.
		history = list(reversed(rows[1:])) if rows else []
		out: list[dict] = []
		for r in history:
			content = (r.get("content") or "").strip()
			role = r.get("role")
			if not content or role not in ("user", "assistant"):
				continue
			if r.get("message_type") == "status":
				continue
			if r.get("status") in ("running", "error", "cancelled"):
				continue
			# A proposed plan is persisted as just its headline (its sections and palette live
			# in metadata, rendered separately by the chat UI). Without them here, the model sees
			# only a one-line headline and can't tell it already proposed a full plan — so on
			# approval it re-proposes instead of building. Restore the full plan into context.
			if role == "assistant" and r.get("status") == "plan_summary":
				content = self._plan_context_content(content, r.get("metadata_json"))
			out.append({"role": role, "content": content})
		return out

	@staticmethod
	def _plan_context_content(headline: str, metadata_json: str | None) -> str:
		"""Reconstruct a proposed plan's full text (headline + sections + palette) from its
		stored metadata, for replay into the model's context."""
		try:
			meta = json.loads(metadata_json) if metadata_json else {}
		except (json.JSONDecodeError, TypeError):
			meta = {}
		if not isinstance(meta, dict):
			return headline
		data_plan = [str(s).strip() for s in (meta.get("data_plan") or []) if str(s).strip()]
		layout_plan = [str(s).strip() for s in (meta.get("layout_plan") or []) if str(s).strip()]
		palette = (meta.get("palette") or "").strip()
		lines = [headline]
		if data_plan:
			lines.append("Data plan:")
			lines.extend(f"- {s}" for s in data_plan)
		if layout_plan:
			lines.append("Layout plan:")
			lines.extend(f"- {s}" for s in layout_plan)
		if palette:
			lines.append(f"Palette: {palette}")
		return "\n".join(lines)

	# --- message write ----------------------------------------------------

	def append_message(
		self,
		role: str,
		content: str,
		*,
		message_type: str = "chat",
		task_type: str | None = None,
		component_id: str | None = None,
		metadata: dict | None = None,
	):
		metadata = metadata or {}
		# Hoist status to its own column for cheap filtered queries; keep
		# everything else in metadata_json.
		status = ""
		meta_clean: dict = {}
		if isinstance(metadata, dict):
			status = (metadata.get("status") or "").strip()
			meta_clean = {k: v for k, v in metadata.items() if k != "status"}

		message = frappe.get_doc(
			{
				"doctype": self.MESSAGE_DOCTYPE,
				"session": self._doc.name,
				"role": role,
				"content": content,
				"message_type": message_type,
				"status": status,
				"task_type": task_type or "",
				"component_id": component_id or "",
				"metadata_json": json.dumps(meta_clean, separators=(",", ":")) if meta_clean else "",
			}
		).insert(ignore_permissions=True)

		# Touch the parent's bookkeeping fields atomically (no full re-save).
		updates: dict = {"last_interaction_on": frappe.utils.now_datetime()}
		if task_type:
			updates["last_task_type"] = task_type
		frappe.db.set_value(self.DOCTYPE, self._doc.name, updates, update_modified=False)
		return message.name

	def update_last_assistant_metadata(self, extra_metadata: dict):
		"""Merge extra_metadata into the most recent assistant message's
		metadata_json. One-row UPDATE — no read-modify-write of a giant blob."""
		row = frappe.db.get_value(
			self.MESSAGE_DOCTYPE,
			{"session": self._doc.name, "role": "assistant"},
			["name", "metadata_json"],
			order_by="creation desc",
			as_dict=True,
		)
		if not row:
			return
		try:
			meta = json.loads(row.metadata_json) if row.metadata_json else {}
		except (json.JSONDecodeError, TypeError):
			meta = {}
		if not isinstance(meta, dict):
			meta = {}
		meta.update(extra_metadata or {})
		frappe.db.set_value(
			self.MESSAGE_DOCTYPE,
			row.name,
			"metadata_json",
			json.dumps(meta, separators=(",", ":")),
			update_modified=False,
		)

	def maybe_name_session(self, model: str, api_key: str | None) -> None:
		"""Give an untitled session a short LLM-written title after its first
		completed turn. Fire-and-forget: a failure just leaves it untitled."""
		if self._doc.title:
			return
		prompt = frappe.db.get_value(
			self.MESSAGE_DOCTYPE,
			{"session": self._doc.name, "role": "user"},
			"content",
			order_by="creation asc",
		)
		if not prompt:
			return
		try:
			from studio.ai import llm

			title = llm.complete(
				model,
				[
					{
						"role": "user",
						"content": f"Name this app-building chat in 3-5 plain words, no quotes:\n{prompt[:500]}",
					}
				],
				{"max_tokens": 24, "temperature": 0.2},
				stream=False,
				api_key=api_key,
			)
			if title := (title or "").strip().strip('"')[:60]:
				frappe.db.set_value(self.DOCTYPE, self._doc.name, "title", title, update_modified=False)
		except Exception:
			pass

	def truncate_from_turn(self, message_id: str):
		"""Rewind the conversation to before the turn containing `message_id`:
		delete the turn's user prompt, its assistant reply, and everything after."""
		anchor = frappe.db.get_value(
			self.MESSAGE_DOCTYPE, {"name": message_id, "session": self._doc.name}, "creation"
		)
		if not anchor:
			frappe.throw(_("Message not found in this session"))
		# The nearest user message at or before the anchor starts the turn.
		turn_start = frappe.db.get_value(
			self.MESSAGE_DOCTYPE,
			{"session": self._doc.name, "role": "user", "creation": ["<=", anchor]},
			"creation",
			order_by="creation desc",
		)
		frappe.db.delete(
			self.MESSAGE_DOCTYPE,
			{"session": self._doc.name, "creation": [">=", turn_start or anchor]},
		)

	# --- lifecycle --------------------------------------------------------

	def clear(self):
		"""Wipe all messages for this session and reset transient state."""
		frappe.db.delete(self.MESSAGE_DOCTYPE, {"session": self._doc.name})
		frappe.db.set_value(
			self.DOCTYPE,
			self._doc.name,
			{
				"last_task_type": None,
				"last_interaction_on": frappe.utils.now_datetime(),
			},
			update_modified=False,
		)
