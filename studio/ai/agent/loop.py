"""The single agentic loop for Studio AI.

`AgentRunner` holds the per-request state, builds the message list, and drives
one tool-calling loop until the model stops requesting server/terminal tools.
Tool *behaviour* lives in the registry; this file only orchestrates.

Realtime event contract (consumed by the frontend). Every event name is
suffixed with the SESSION id, e.g. `ai_chat_stream_<session_id>` — the chat
panel follows its session, so navigating between pages never detaches a
running turn:

    ai_chat_progress    {message}
    ai_chat_stream      {chunk, kind?}   append to the chat reply text;
                                         kind="reasoning" → the open thinking step
    ai_chat_step        {id, kind: "thinking"|"tool"|"text", status: "running"|"done",
                         summary?, text?, ms?, tool?}
                        One entry of the turn's timeline; the same id is emitted
                        twice (running then done), so upsert by id.
    ai_chat_tool_batch  {operations: [{tool_name, args}]}   mirror on the canvas —
                        ONLY when target_page_id is the page open in the editor
    ai_chat_page        {action: "created"|"meta"|"updated", name, title, route, modified}
                        a page this turn touched — render an open-page link;
                        `modified` lets an editor showing that page sync its timestamp
    ai_chat_complete    {message}
    ai_chat_error       {message}

All events also carry {page_id, target_page_id}: page_id is the page open at
submit time, target_page_id the page the loop is currently WRITING to. Ops are
applied and persisted server-side to the target page (see WorkingTree) — the
canvas is a live viewer, never the write target.
"""

import json
import logging
import re
import time

import frappe

from studio.ai import llm, locks, snapshots
from studio.ai.agent.registry import get_tool_registry_for_mode
from studio.ai.agent.tree import WorkingTree
from studio.ai.block_codec import BlockCodec
from studio.ai.models import ModelRegistry
from studio.ai.prompts import get_system_prompt_for_mode
from studio.ai.session import AISession

logger = frappe.logger("studio.ai.agent.loop")
logger.setLevel(logging.INFO)

# One turn may span several rounds: server-tool reads plus a model that applies a
# change in batches. High enough to finish a big multi-block edit, bounded so a runaway
# loop can't spin.
MAX_ROUNDS = 40
EVENT_PREFIX = "ai_chat"

# A streaming round is retried on transient failure (litellm can't fall back mid-stream).
# Backoff is STREAM_BACKOFF_BASE * 2**attempt → ~1s, 2s before the final give-up.
STREAM_MAX_ATTEMPTS = 3
STREAM_BACKOFF_BASE = 1.0


class CancelledError(Exception):
	"""Raised inside the stream loop when the user cancels the turn."""


# Tools that shouldn't appear in the visible timeline (they render as their own
# chat card instead).
ACTIVITY_SILENT = frozenset(
	{"ask_clarification", "propose_plan", "create_doctype", "seed_sample_data", "write_python_file"}
)

# Server tools that only READ. Everything else that runs server-side mutates real
# state — those turns get a revert snapshot even when no canvas op was applied.
READ_ONLY_SERVER_TOOLS = frozenset(
	{
		"query_blocks",
		"read_block",
		"get_page_state",
		"list_doctypes",
		"get_doctype_fields",
		"get_sort_fields",
		"get_whitelisted_methods",
		"list_data_sources",
		"get_page_script",
		"list_variables",
		"list_app_files",
		"read_app_file",
		"list_pages",
		"read_page",
		"preview_page",
		"get_page_errors",
		"read_skill",
		"search_images",
		"query_records",
		"get_document",
		"run_python",
		"list_backend_files",
		"read_backend_file",
	}
)

# Past-tense claims of applied work. Used to catch a model narrating success
# with zero ops applied — the most corrosive failure mode a chat agent has.
ACTION_CLAIM_RE = re.compile(
	r"\b(added|updated|changed|created|built|removed|moved|wired|applied|fixed|restyled|redesigned)\b",
	re.IGNORECASE,
)

UNBACKED_CORRECTION = (
	"CORRECTION: your last message claims changes, but NO tool call was applied this turn. "
	"Either make the changes now by calling the tools, or reply honestly that nothing was changed. "
	"Never describe work you did not do."
)

TOOL_LABELS = {
	"generate_page": "Building the page",
	"query_blocks": "Scanned the page",
	"get_page_state": "Checked page data",
	"list_doctypes": "Browsed doctypes",
	"get_sort_fields": "Checked sortable fields",
	"get_whitelisted_methods": "Checked available methods",
	"list_data_sources": "Read data sources",
	"add_data_source": "Added a data source",
	"update_data_source": "Updated a data source",
	"delete_data_source": "Removed a data source",
	"get_page_script": "Read the page script",
	"set_page_script": "Updated the page script",
	"list_variables": "Read variables",
	"add_variable": "Added a variable",
	"update_variable": "Updated a variable",
	"delete_variable": "Removed a variable",
	"list_app_files": "Browsed app files",
	"trigger_app_build": "Queued an app build",
	"preview_page": "Looked at the page",
	"read_skill": "Read reference docs",
	"search_images": "Searched stock photos",
	"query_records": "Read real records",
	"get_document": "Read a record",
	"run_python": "Ran a read query",
	"list_backend_files": "Browsed backend files",
	"read_backend_file": "Read backend code",
	"list_pages": "Listed the app's pages",
	"create_page": "Created a page",
	"open_page": "Switched working page",
	"set_page_meta": "Updated page title/route",
}


def activity_summary(tool_name: str, args: dict) -> str:
	"""A short human line for the chat's timeline ("Read block: hero"). Written for
	someone who asked for an app, not someone who knows the tool API."""
	args = args or {}
	if label := TOOL_LABELS.get(tool_name):
		return label
	if tool_name == "read_block":
		return f"Read block: {args.get('component_id') or ''}".rstrip(": ")
	if tool_name in ("update_block", "update_blocks", "add_block", "remove_block", "move_block"):
		verb = tool_name.split("_")[0].capitalize()
		target = args.get("component_id") or ""
		return f"{verb} block{'s' if tool_name == 'update_blocks' else ''}: {target}".rstrip(": ")
	if tool_name == "get_doctype_fields":
		return f"Checked the {args['doctype']} fields" if args.get("doctype") else "Checked the data fields"
	if tool_name in ("read_app_file", "write_app_file", "delete_app_file"):
		verb = {"read_app_file": "Read", "write_app_file": "Wrote", "delete_app_file": "Deleted"}[tool_name]
		return f"{verb} {args.get('path') or 'a file'}"
	return tool_name.replace("_", " ").capitalize()


class AgentRunner:
	def __init__(
		self,
		prompt: str,
		page_context_json: str,
		model: str,
		api_key: str,
		*,
		user: str | None = None,
		app_id: str | None = None,
		page_id: str | None = None,
		session_id: str | None = None,
		selected_block_ids: list[str] | None = None,
		image_url: str | None = None,
	):
		self.prompt = prompt
		self.page_context_json = page_context_json
		self.model = model
		self.api_key = api_key
		self.user = user or frappe.session.user
		self.app_id = app_id or (
			page_id and frappe.db.get_value("Studio Page", page_id, "studio_app") or None
		)
		self.page_id = page_id
		self.session_id = session_id
		self.selected_block_ids = selected_block_ids or []
		# An optional screenshot/design (base64 data URL) to reproduce; attached to this turn's
		# user message so the model can see it (see build_messages).
		self.image_url = image_url
		# Pages whose draft this turn has written — once persisted, the DB copy is
		# fresher than the submit-time canvas context (see switch_target).
		self._persisted_pages: set[str] = set()
		is_standard = self.is_standard()
		self.registry = get_tool_registry_for_mode(is_standard)
		self.system_prompt = get_system_prompt_for_mode(is_standard)
		self.tree: WorkingTree | None = None
		# The page the agent is currently building — starts as the editor's open page.
		# create_page/open_page switch it; background pages get server-side persistence.
		self.target_page_id = page_id
		# Pages this turn created/updated — persisted on the reply for link chips.
		self.page_events: list[dict] = []
		# The turn's timeline, streamed to the chat as ai_chat_step events and persisted
		# on the final message: the tools the model ran, its reasoning, and the narration
		# it wrote between rounds — in the order they happened.
		self.steps: list[dict] = []
		self.step_starts: dict[int, float] = {}
		self._open_thinking: dict | None = None

	def is_standard(self) -> bool:
		"""Pages inherit is_standard from their app, so the app answers for every
		page this session might touch."""
		if self.app_id:
			return bool(frappe.db.get_value("Studio App", self.app_id, "is_standard"))
		if self.page_id:
			return bool(frappe.db.get_value("Studio Page", self.page_id, "is_standard"))
		return False

	# --- cancellation -----------------------------------------------------

	def _cancel_key(self) -> str | None:
		return f"studio_ai_cancel:{self.session_id}" if self.session_id else None

	def is_cancelled(self) -> bool:
		key = self._cancel_key()
		# use_local_cache=False is critical: the cancel is set by a DIFFERENT web worker,
		# and Frappe's per-request local cache would otherwise pin the first (miss) result.
		return bool(frappe.cache.get_value(key, use_local_cache=False)) if key else False

	def clear_cancel_flag(self) -> None:
		if key := self._cancel_key():
			frappe.cache.delete_value(key)

	def interruptible_sleep(self, seconds: float) -> None:
		"""Sleep in small steps so a cancel during retry backoff is honored within ~0.25s."""
		waited = 0.0
		while waited < seconds:
			if self.is_cancelled():
				raise CancelledError
			step = min(0.25, seconds - waited)
			time.sleep(step)
			waited += step

	# --- realtime ---------------------------------------------------------

	def emit(self, suffix: str, **kwargs):
		"""Events ride a session-keyed channel: the chat panel follows its session,
		so navigating between pages never detaches a running turn."""
		event = f"{EVENT_PREFIX}_{suffix}"
		channel = self.session_id or self.page_id
		if channel:
			event = f"{event}_{channel}"
		frappe.publish_realtime(
			event,
			{"page_id": self.page_id, "target_page_id": self.target_page_id, **kwargs},
			user=self.user,
		)

	# --- working page -----------------------------------------------------

	def switch_target(self, page_name: str) -> None:
		"""Point the loop at another page of the app. Ops apply to the target
		server-side wherever the user is; the canvas mirrors them only while that
		page is open in the editor. The editor page seeds from the submit-time
		canvas copy (freshest, may hold unsaved edits) until this turn has
		persisted it — after that the DB is fresher."""
		self.target_page_id = page_name
		if page_name == self.page_id and page_name not in self._persisted_pages:
			self.tree = WorkingTree(self._page_root())
		else:
			self.tree = WorkingTree(self._db_page_root(page_name))

	@staticmethod
	def _db_page_root(page_name: str) -> dict | None:
		raw = frappe.db.get_value("Studio Page", page_name, "draft_blocks") or frappe.db.get_value(
			"Studio Page", page_name, "blocks"
		)
		try:
			blocks = json.loads(raw or "[]")
		except (json.JSONDecodeError, TypeError):
			return None
		if isinstance(blocks, list):
			return blocks[0] if blocks else None
		return blocks if isinstance(blocks, dict) else None

	def note_page_event(self, action: str, doc) -> None:
		"""Record a page this turn touched (created / meta / updated) — streamed live
		and persisted on the reply so the chat can render an open-page link. Re-emits
		replace the previous same-action entry (each persist refreshes `modified`)."""
		event = {
			"action": action,
			"name": doc.name,
			"title": doc.page_title,
			"route": doc.route,
			"modified": str(doc.modified),
		}
		self.page_events = [
			e for e in self.page_events if not (e["name"] == doc.name and e["action"] == action)
		] + [event]
		self.emit("page", **event)

	def persist_tree(self) -> None:
		"""Write the applied tree to the target page's draft. Agent writes land in
		the DB — the page they are ADDRESSED to — never in "whatever canvas is
		open"; an editor showing this page syncs its timestamp from the page event
		and mirrors the ops live, any other editor state is simply unaffected."""
		if not self.target_page_id or self.tree is None or self.tree.root is None:
			return
		doc = frappe.get_doc("Studio Page", self.target_page_id)
		doc.draft_blocks = BlockCodec.to_json([self.tree.root])
		doc.save(ignore_permissions=True)
		self._persisted_pages.add(self.target_page_id)
		self.note_page_event("updated", doc)

	def apply_generated(self, op: dict) -> None:
		"""A generation replaces the whole target page: assign ids server-side,
		adopt it as the turn's tree, persist."""
		block = (op.get("args") or {}).get("block")
		if not block:
			return
		BlockCodec.ensure_ids(block)
		self.tree = WorkingTree(block)
		self.persist_tree()

	# --- turn timeline ----------------------------------------------------

	def add_step(self, kind: str, **fields) -> dict:
		"""Append one timeline entry and stream it. Steps are upserted client-side by
		id, so a running step is finished by re-emitting the same entry."""
		step = {"id": len(self.steps), "kind": kind, **fields}
		self.steps.append(step)
		self.emit("step", **step)
		return step

	def finish_step(self, step: dict | None, started: float | None = None, **fields) -> None:
		if step is None:
			return
		step["status"] = "done"
		if started is not None:
			step["ms"] = round((time.monotonic() - started) * 1000)
		step.update(fields)
		self.emit("step", **step)

	def timeline(self) -> list[dict]:
		"""The steps worth keeping on the message: tools, narration with text, and
		thinking that actually carries reasoning (an empty one would replay as a stall)."""
		return [
			s
			for s in self.steps
			if (s.get("kind") == "tool")
			or (s.get("kind") == "text" and s.get("text"))
			or (s.get("kind") == "thinking" and s.get("text"))
		]

	def begin_activity(self, tool_name: str, args: dict) -> dict | None:
		if tool_name in ACTIVITY_SILENT:
			return None
		entry = self.add_step(
			"tool", tool=tool_name, summary=activity_summary(tool_name, args), status="running"
		)
		self.step_starts[entry["id"]] = time.monotonic()
		return entry

	def end_activity(self, entry: dict | None) -> None:
		if entry is not None:
			self.finish_step(entry, self.step_starts.pop(entry["id"], None))

	def flush_pending_images(self, messages: list[dict]) -> None:
		"""Screenshots queued by preview_page ride a follow-up USER message after the
		round's tool results — the OpenAI tool-result shape can't carry image parts."""
		if not self.pending_images:
			return
		content: list[dict] = []
		for image in self.pending_images:
			content.append({"type": "text", "text": image["caption"]})
			content.append({"type": "image_url", "image_url": {"url": image["data_url"]}})
		messages.append({"role": "user", "content": content})
		self.pending_images = []

	def checkpoint(self) -> None:
		"""Make this round's work durable. A turn runs as a background job, and a job
		that raises rolls the WHOLE transaction back — without this, a provider
		timeout in round 7 would discard the data sources, scripts and messages
		written in rounds 1-6. It also lets the editor and the chat, both separate
		requests, see a long turn progress instead of nothing until it ends. One
		commit per round: individual tools never commit."""
		frappe.db.commit()  # nosemgrep

	# --- message construction --------------------------------------------

	def _page_root(self) -> dict | None:
		"""Parse page_context_json into the root block dict, or None if empty/invalid."""
		try:
			data = json.loads(self.page_context_json)
		except (json.JSONDecodeError, TypeError):
			return None
		if isinstance(data, list):
			data = data[0] if data else None
		return data if isinstance(data, dict) else None

	def build_page_context(self) -> str:
		root = self._page_root()
		if root is None:
			return ""
		structure = BlockCodec.to_json(BlockCodec.compress(root))
		return f"Current page structure (JSON — pass a block's 'id' value as component_id to edit it):\n{structure}"

	def build_messages(self) -> list[dict]:
		messages: list[dict] = [
			{"role": "system", "content": self.system_prompt, "cache_control": {"type": "ephemeral"}},
		]
		if page_context_message := self.build_page_context():
			# Cache the page structure too (the system prompt is the other breakpoint): it's
			# the largest stable block, resent every round of a multi-round edit, so caching
			# it cuts both latency and input cost across the loop.
			messages.append(
				{"role": "user", "content": page_context_message, "cache_control": {"type": "ephemeral"}}
			)
			messages.append(
				{
					"role": "assistant",
					"content": "Understood. I have the current page structure. What would you like me to change?",
				}
			)
		# Prior conversation as proper role-tagged turns (the model handles dialogue better
		# and we save the "User:"/"Assistant:" prefix tokens on every call).
		messages.extend(AISession.build_context_messages_from_id(self.session_id))
		user_text = self.prompt
		if self.selected_block_ids:
			user_text += f"\n\n(User has selected: {', '.join(self.selected_block_ids)})"
		if self.image_url and ModelRegistry.is_vision_capable(self.model):
			# Multimodal message: the model sees the attached screenshot alongside the prompt.
			messages.append(
				{
					"role": "user",
					"content": [
						{"type": "text", "text": user_text},
						{"type": "image_url", "image_url": {"url": self.image_url}},
					],
				}
			)
		else:
			messages.append({"role": "user", "content": user_text})
		return messages

	# --- LLM call ---------------------------------------------------------

	def call_tool_llm(self, messages: list[dict]) -> tuple[list[dict], str, list[dict]]:
		"""Stream one tool-calling round, retrying the WHOLE round on a transient stream
		failure. Safe because a round applies nothing until it returns — ops are emitted and
		`messages` mutated by the caller only after this returns, so a failed attempt leaves
		no partial state; we just re-issue the identical completion (the cached prefix makes
		the retry cheap). litellm can't fall back mid-stream, so this is the retry layer."""
		for attempt in range(STREAM_MAX_ATTEMPTS):
			try:
				return self.stream_tool_round(messages)
			except CancelledError:
				raise
			except Exception as exc:
				# A thinking step opened by the failed attempt would otherwise spin forever.
				if self._open_thinking is not None:
					self.finish_step(self._open_thinking)
					self._open_thinking = None
				if attempt == STREAM_MAX_ATTEMPTS - 1 or not llm.is_retryable(exc):
					raise
				backoff = STREAM_BACKOFF_BASE * (2**attempt)
				logger.warning(
					"Stream round failed (attempt %d/%d): %s — retrying in %.1fs",
					attempt + 1,
					STREAM_MAX_ATTEMPTS,
					exc,
					backoff,
				)
				self.interruptible_sleep(backoff)

	def stream_tool_round(self, messages: list[dict]) -> tuple[list[dict], str, list[dict]]:
		"""Stream one tool-calling completion. Returns (tool_operations, text_content,
		raw_tool_calls). Side-effect-free until it returns (see call_tool_llm) — accumulates
		into locals only, so it is safe to re-run. Tool-call arguments are accumulated by
		index across chunks."""
		stream = llm.complete_with_tools(
			self.model,
			messages,
			self.registry.schemas(),
			llm.TASK_PARAMS["agent"],
			api_key=self.api_key,
			stream=True,
		)

		content_parts: list[str] = []
		# index -> {"id", "name", "args"}; preserves call order across chunks.
		acc: dict[int, dict] = {}
		finish_reason = None

		for chunk in stream:
			if self.is_cancelled():
				try:
					stream.close()
				except Exception:
					pass
				raise CancelledError
			# The final include_usage chunk carries usage but no choices.
			if not chunk.choices:
				continue
			if fr := chunk.choices[0].finish_reason:
				finish_reason = fr
			delta = chunk.choices[0].delta
			# Models that stream reasoning get a live thinking step; the text rides
			# along so a reload can replay it from the persisted timeline.
			if reasoning := getattr(delta, "reasoning_content", None):
				if self._open_thinking is None:
					self._open_thinking = self.add_step("thinking", status="running", text="")
				self._open_thinking["text"] = (self._open_thinking.get("text") or "") + reasoning
				self.emit("stream", chunk=reasoning, kind="reasoning")
			if getattr(delta, "content", None):
				content_parts.append(delta.content)
			for tc in getattr(delta, "tool_calls", None) or []:
				idx = tc.index if tc.index is not None else 0
				entry = acc.setdefault(idx, {"id": None, "name": None, "args": ""})
				if tc.id:
					entry["id"] = tc.id
				fn = getattr(tc, "function", None)
				if fn and fn.name:
					entry["name"] = fn.name
				if fn and fn.arguments:
					entry["args"] += fn.arguments

		tool_operations: list[dict] = []
		raw_tool_calls: list[dict] = []
		for idx in sorted(acc):
			entry = acc[idx]
			if not entry["name"]:
				continue
			raw_arguments = entry["args"] or ""
			parsed, repaired = llm.loads_tolerant(raw_arguments)
			args = parsed if isinstance(parsed, dict) else {}
			if parsed is None:
				logger.warning("AI tool args UNPARSEABLE (tool=%s): %s", entry["name"], raw_arguments[:2000])
			elif repaired:
				logger.warning("AI tool args recovered via json_repair (tool=%s)", entry["name"])
			tool_operations.append({"tool_name": entry["name"], "args": args})
			raw_tool_calls.append(
				{
					"id": entry["id"],
					"type": "function",
					"function": {"name": entry["name"], "arguments": raw_arguments},
				}
			)

		if self._open_thinking is not None:
			self.finish_step(self._open_thinking)
			self._open_thinking = None

		content = "".join(content_parts)
		if finish_reason == "length":
			logger.warning("Agent LLM hit max_tokens (finish_reason=length) — tool args may be truncated")
		logger.info(
			"Agent LLM responded: tool_calls=%d, has_text=%s, finish_reason=%s",
			len(tool_operations),
			bool(content),
			finish_reason,
		)
		return tool_operations, content, raw_tool_calls

	@staticmethod
	def describe_operations(operations: list[dict]) -> str:
		"""A deterministic one-line summary of applied ops — used when the model didn't
		return its own summary text, so we avoid a second LLM round trip."""
		from collections import Counter

		counts = Counter(op.get("tool_name") for op in operations)

		def blk(n: int) -> str:
			return "block" if n == 1 else "blocks"

		if counts.get("generate_page"):
			return (
				"Created the page. Ask me to refine it — adjust styles, add sections, or change the layout."
			)

		# update_blocks edits many blocks in one op — count the blocks it touched.
		batched = 0
		for op in operations:
			if op.get("tool_name") != "update_blocks":
				continue
			args = op.get("args") or {}
			patches = args.get("patches")
			batched += len(patches) if isinstance(patches, list) else len(args.get("component_ids") or [])

		parts: list[str] = []
		if n := (counts.get("update_block", 0) + batched):
			parts.append(f"updated {n} {blk(n)}")
		if n := counts.get("add_block"):
			parts.append(f"added {n} {blk(n)}")
		if n := counts.get("remove_block"):
			parts.append(f"removed {n} {blk(n)}")
		if n := counts.get("move_block"):
			parts.append(f"moved {n} {blk(n)}")
		if n := (counts.get("bind_prop", 0) + counts.get("set_repeater_data", 0)):
			parts.append(f"wired {n} binding{'s' if n != 1 else ''}")

		if not parts:
			n = len(operations)
			return f"Applied {n} change{'s' if n != 1 else ''} to the page."
		sentence = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
		return sentence[0].upper() + sentence[1:] + "."

	# --- orchestration ----------------------------------------------------

	def run(self):
		"""Acquire the turn's locks, then drive the loop. One turn per session, one
		writer per page — both atomic and self-expiring, so a crashed worker can
		never wedge them (see studio.ai.locks)."""
		with locks.guard(locks.session_key(self.session_id or "-"), locks.SESSION_LOCK_TTL) as got:
			if not got:
				logger.warning("AgentRunner.run: session %s already running, rejecting", self.session_id)
				self.emit(
					"error", message="Another AI request is still processing. Please wait for it to finish."
				)
				return
			with locks.guard(locks.page_key(self.page_id or "-"), locks.PAGE_LOCK_TTL) as page_got:
				if not page_got:
					self.emit("error", message="Another AI request is editing this page. Please wait.")
					return
				self.run_turn()

	def run_turn(self):
		# Clear any stale cancel flag from a previous turn before starting.
		self.clear_cancel_flag()
		label = ModelRegistry.get_label(self.model)
		self.emit("progress", message=f"Thinking with {label}…" if label else "Thinking…")

		messages = self.build_messages()
		# Mirror of the page tree this turn. Client ops are validated against it so the tool
		# result fed back is the truth, not a blanket "Applied." (see WorkingTree).
		self.tree = WorkingTree(self._page_root())
		# Pre-turn page state, saved as a revert snapshot only if this turn mutates.
		self.pending_state = snapshots.capture_page_state(self.page_id)
		self.server_mutations = 0
		# Screenshots queued by preview_page this round — flushed as a follow-up user
		# message after the tool results (tool results can't carry image parts).
		self.pending_images: list[dict] = []
		self.preview_count = 0
		# Every photo search_images turned up this turn, handed to the generation step
		# so the page can use any of them without the model retyping urls into a brief.
		self.found_images: list[dict] = []
		client_operations: list[dict] = []
		summary_text = ""
		corrected_unbacked = False

		try:
			for _round in range(MAX_ROUNDS):
				tool_operations, summary_text, raw_tool_calls = self.call_tool_llm(messages)
				terminal_ops, artifact_ops, server_ops, client_ops = self._classify(tool_operations)

				# A terminal tool ends the turn and hands control back to the user. If the
				# model emits more than one, the first wins (the turn is over).
				if terminal_ops:
					self.handle_terminal(terminal_ops[0])
					return

				# An artifact tool (full-page generation) is the turn's work: its generator
				# streams the artifact live on the heavy model and returns the canonical client
				# op(s), persisted server-side and mirrored to the canvas. Generation ends the loop.
				if artifact_ops:
					for op in artifact_ops:
						tool = self.registry.get(op["tool_name"])
						if tool and tool.generator:
							entry = self.begin_activity(op["tool_name"], op["args"])
							ops = tool.generator(self, op["args"])
							self.end_activity(entry)
							client_operations.extend(ops)
							for gen_op in ops:
								self.apply_generated(gen_op)
							if ops:
								self.emit("tool_batch", operations=ops)
					break

				# Live narration: surface what the model said / did THIS round, and keep
				# it on the timeline so a reload can replay it.
				if tool_operations:
					note = (summary_text or "").strip() or (
						self.describe_operations(client_ops) if client_ops else ""
					)
					if note:
						self.add_step("text", text=note, status="done")
						self.emit("progress", message=note)

				# The model ENDS the turn by replying with a final summary and NO tool calls.
				if not tool_operations:
					# One corrective round when the summary claims work nothing backs.
					if (
						not corrected_unbacked
						and summary_text
						and not client_operations
						and not self.server_mutations
						and ACTION_CLAIM_RE.search(summary_text)
					):
						corrected_unbacked = True
						messages.append({"role": "assistant", "content": summary_text})
						messages.append({"role": "user", "content": UNBACKED_CORRECTION})
						continue
					break

				# Feed each tool's result back so the model can continue or self-correct.
				messages.append(
					{"role": "assistant", "content": summary_text or None, "tool_calls": raw_tool_calls}
				)
				for tc_dict, op in zip(raw_tool_calls, tool_operations, strict=True):
					tool = self.registry.get(op["tool_name"])
					entry = self.begin_activity(op["tool_name"], op["args"])
					if tool and tool.side == "server" and tool.handler:
						content = tool.handler(self, op["args"])
						if op["tool_name"] not in READ_ONLY_SERVER_TOOLS and not content.startswith("FAILED"):
							self.server_mutations += 1
					else:
						content = self.tree.apply(op["tool_name"], op["args"])
						# "FAILED" (hard miss) or "NOT FOUND" (partial bulk miss) — a correction
						# the model is now being asked to make. Log so it's not invisible.
						if "FAILED" in content or "NOT FOUND" in content:
							logger.warning("Client op rejected — %s: %s", op["tool_name"], content)
					self.end_activity(entry)
					messages.append({"role": "tool", "tool_call_id": tc_dict["id"], "content": content})

				# Emit AFTER application so add_block/set_slot args carry the ids the tree
				# assigned (the canvas builds the same ids the draft stores), then make the
				# round durable on the target page. The canvas mirror is gated client-side
				# by target_page_id — a page open elsewhere simply ignores the batch.
				if client_ops:
					client_operations.extend(client_ops)
					self.emit("tool_batch", operations=client_ops)
					self.persist_tree()

				self.flush_pending_images(messages)

				# One commit per round: makes this round's server-tool writes and messages
				# durable, so a provider failure in a later round can't roll them back.
				self.checkpoint()

		except CancelledError:
			self._emit_cancelled()
			return
		except Exception as e:
			logger.error(f"Agent LLM call failed: {e!s}", exc_info=True)
			frappe.log_error(f"Agent LLM call failed: {e}", "AgentRunner.run")
			# Show a generic message — raw provider/exception strings can leak internals.
			user_msg = "Something went wrong while building your changes. Please try again."
			AISession.try_append_message(
				self.session_id,
				"assistant",
				user_msg,
				message_type="status",
				metadata={"status": "error", "steps": self.timeline()},
			)
			frappe.db.commit()  # commit before emit so the client's reload sees it
			self.emit("error", message=user_msg)
			return
		finally:
			self.clear_cancel_flag()

		if not client_operations and not summary_text:
			logger.warning("Agent returned empty response (no tools, no text)")
			self.emit("error", message="The AI returned an empty response. Please try rephrasing.")
			return

		# The block edits were already emitted incrementally inside the loop. If the model
		# wrote no summary, synthesise one from the ops rather than making a second LLM call.
		if not summary_text:
			summary_text = self.describe_operations(client_operations)
		# Final backstop: a summary still claiming work nothing backs is rewritten to
		# the truth rather than persisted as a lie.
		if (
			summary_text
			and not client_operations
			and not self.server_mutations
			and ACTION_CLAIM_RE.search(summary_text)
		):
			summary_text = "I looked into it but didn't apply any changes. Tell me how you'd like to proceed."
		self.emit("stream", chunk=summary_text)

		# Offer revert only for turns that changed something.
		snapshot_name = None
		if client_operations or self.server_mutations:
			snapshot_name = snapshots.save_revert_snapshot(self.page_id, self.pending_state, self.session_id)

		AISession.try_append_message(
			self.session_id,
			"assistant",
			summary_text or "Done",
			message_type="chat",
			task_type="agent",
			metadata={
				"status": "complete",
				"model": self.model,
				"operations": len(client_operations),
				"steps": self.timeline(),
				**({"pages": self.page_events} if self.page_events else {}),
				**({"revertSnapshot": snapshot_name} if snapshot_name else {}),
			},
		)
		frappe.db.commit()  # commit before emit so the client's reload sees the final turn
		self.emit("complete", message=summary_text or "Done")

		if self.session_id and frappe.db.exists(AISession.DOCTYPE, self.session_id):
			AISession(frappe.get_doc(AISession.DOCTYPE, self.session_id)).maybe_name_session(
				self.model, self.api_key
			)
			frappe.db.commit()

	def _classify(self, tool_operations: list[dict]) -> tuple[list, list, list, list]:
		"""Split this round's calls. Artifact tools (generate_page) are handled by their
		generator and take precedence over their nominal side; client ops are emitted to the
		canvas; server ops run via their handler; a terminal op ends the turn."""
		terminal_ops, artifact_ops, server_ops, client_ops = [], [], [], []
		for op in tool_operations:
			tool = self.registry.get(op["tool_name"])
			if tool and tool.artifact:
				artifact_ops.append(op)
				continue
			side = self.registry.side(op["tool_name"])
			if side == "terminal":
				terminal_ops.append(op)
			elif side == "server":
				server_ops.append(op)
			else:
				client_ops.append(op)
		return terminal_ops, artifact_ops, server_ops, client_ops

	def _emit_cancelled(self) -> None:
		msg = "Cancelled."
		AISession.try_append_message(
			self.session_id,
			"assistant",
			msg,
			message_type="status",
			metadata={"status": "cancelled", "steps": self.timeline()},
		)
		frappe.db.commit()
		self.emit("complete", message=msg)

	def handle_terminal(self, op: dict):
		"""Run a terminal tool's handler (which emits the appropriate event and persists
		the message). Terminal tools register a handler. The turn's timeline is attached
		to whatever message the handler persisted, so a reload can replay it."""
		tool = self.registry.get(op["tool_name"])
		if tool and tool.handler:
			tool.handler(self, op["args"])
		if steps := self.timeline():
			AISession.attach_metadata_to_last_assistant(self.session_id, {"steps": steps})
			frappe.db.commit()


def run_agent_job(prompt: str, page_context_json: str, model: str, api_key: str, **kwargs):
	AgentRunner(prompt, page_context_json, model, api_key, **kwargs).run()
