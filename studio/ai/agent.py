import json
import logging

import frappe
import litellm
from frappe import _

from studio.ai.block_codec import BlockCodec
from studio.ai.models import ModelRegistry
from studio.ai.page_generator import COMPONENT_CATALOG, STYLING_RULES, YAML_QUOTING_RULES, _emit
from studio.ai.session import AISession
from studio.utils import has_page_write_perm

litellm.drop_params = True
logger = frappe.logger("studio.ai")
logger.setLevel(logging.INFO)

MAX_TURNS = 15

BLOCK_TOOLS = [
	{
		"type": "function",
		"function": {
			"name": "update_block",
			"description": "Merge style and prop changes into an existing block without replacing it",
			"parameters": {
				"type": "object",
				"properties": {
					"component_id": {"type": "string", "description": "componentId of the block to update"},
					"base_styles": {
						"type": "object",
						"description": "CSS style properties to merge into baseStyles",
					},
					"mobile_styles": {"type": "object"},
					"tablet_styles": {"type": "object"},
					"component_props": {"type": "object", "description": "Component props to merge"},
					"attributes": {"type": "object"},
				},
				"required": ["component_id"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "add_block",
			"description": "Insert a new child block into the page",
			"parameters": {
				"type": "object",
				"properties": {
					"parent_component_id": {
						"type": "string",
						"description": "componentId of the parent block",
					},
					"block": {
						"type": "object",
						"description": "Block definition in compact format: {name, label, props, style, rstyle, c}",
					},
					"after_component_id": {
						"type": "string",
						"description": "Insert after this sibling (optional)",
					},
					"index": {"type": "integer", "description": "Insert at this index (optional)"},
				},
				"required": ["parent_component_id", "block"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "remove_block",
			"description": "Delete a block and all its descendants",
			"parameters": {
				"type": "object",
				"properties": {
					"component_id": {"type": "string", "description": "componentId of the block to remove"},
				},
				"required": ["component_id"],
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "move_block",
			"description": "Move a block to a different parent or position",
			"parameters": {
				"type": "object",
				"properties": {
					"component_id": {"type": "string", "description": "componentId of the block to move"},
					"new_parent_component_id": {
						"type": "string",
						"description": "componentId of the new parent",
					},
					"after_component_id": {
						"type": "string",
						"description": "Insert after this sibling (optional)",
					},
					"index": {"type": "integer", "description": "Insert at this index (optional)"},
				},
				"required": ["component_id", "new_parent_component_id"],
			},
		},
	},
]

AGENT_SYSTEM_PROMPT = f"""You are an expert UI editor for Frappe Studio. You receive the current page block tree (compact YAML) and a user request. Use the provided tools to make targeted structural changes.

RULES:
- Always use tools to make changes — never describe what to do without calling a tool
- Use exact componentId values from the page structure — never invent IDs
- Make minimal changes — only what the user requested, leave everything else untouched
- After all tool calls are done, write 1–2 sentences summarising what you changed

BLOCK FORMAT for add_block (compact object — same structure as YAML output):
{{
  "name": "componentName",
  "label": "descriptive name",
  "props": {{}},
  "style": {{}},
  "rstyle": {{}},
  "c": []
}}

{COMPONENT_CATALOG}

{STYLING_RULES}

{YAML_QUOTING_RULES}
"""


def _call_agent_llm(messages: list, model: str, api_key: str, tools: list):
	return litellm.completion(
		model=model,
		messages=messages,
		api_key=api_key,
		tools=tools,
		tool_choice="auto",
		max_tokens=16000,
		temperature=0.3,
	)


def run_agent_job(
	prompt: str,
	page_context: str,
	model: str,
	page_id: str,
	user: str,
	selected_component_ids: list | None = None,
):
	settings = frappe.get_single("Studio Settings")
	api_key = settings.get_password("ai_api_key", raise_exception=False)

	session = AISession.get_or_create(page_id, model)
	context = session.build_context_string()
	session.add_message("user", prompt, task_type="agent")

	_emit("progress", page_id, user, prefix="ai_agent", message="Analyzing page…")

	page_yaml = BlockCodec.strip_context(page_context)

	system = AGENT_SYSTEM_PROMPT + (f"\n\nConversation history:\n{context}" if context else "")
	messages = [
		{"role": "system", "content": system},
		{"role": "user", "content": f"Current page structure:\n{page_yaml}\n\nRequest: {prompt}"},
	]

	summary = ""
	try:
		for _turn in range(MAX_TURNS):
			response = _call_agent_llm(messages, model, api_key, BLOCK_TOOLS)
			choice = response.choices[0]
			message = choice.message

			if choice.finish_reason == "tool_calls" and message.tool_calls:
				ops = []
				for tc in message.tool_calls:
					try:
						args = json.loads(tc.function.arguments)
					except json.JSONDecodeError:
						args = {}
					ops.append({"tool_name": tc.function.name, "args": args})

				_emit("tool_batch", page_id, user, prefix="ai_agent", operations=ops)
				_emit("progress", page_id, user, prefix="ai_agent", message=f"Applied {len(ops)} change(s)…")

				messages.append(
					{
						"role": "assistant",
						"content": message.content,
						"tool_calls": [
							{
								"id": tc.id,
								"type": "function",
								"function": {
									"name": tc.function.name,
									# Always a JSON string — some providers return a dict
									"arguments": tc.function.arguments
									if isinstance(tc.function.arguments, str)
									else json.dumps(tc.function.arguments),
								},
							}
							for tc in message.tool_calls
						],
					}
				)
				for tc in message.tool_calls:
					messages.append(
						{"role": "tool", "tool_call_id": tc.id, "content": '{"status": "applied"}'}
					)

			else:
				summary = (message.content or "").strip()
				break

		if summary:
			_emit("stream", page_id, user, prefix="ai_agent", chunk=summary)

		session.add_message("assistant", summary or "Done.", task_type="agent")
		frappe.db.commit()
		_emit("complete", page_id, user, prefix="ai_agent")

	except Exception as e:
		logger.error(f"run_agent_job failed: {e}", exc_info=True)
		frappe.log_error(title="Studio AI: agent error", message=str(e))
		_emit("error", page_id, user, prefix="ai_agent", message=str(e))


@frappe.whitelist()
@has_page_write_perm()
def run_agent_from_prompt(
	prompt: str,
	page_context: str,
	model: str | None,
	page_id: str,
	selected_component_ids: str | None = None,
) -> dict:
	settings = frappe.get_single("Studio Settings")
	if not settings.get_password("ai_api_key", raise_exception=False):
		frappe.throw(_("OpenRouter API key is not configured. Please set it in Studio Settings."))

	resolved_model = model or ModelRegistry.get_default()
	ids = json.loads(selected_component_ids) if selected_component_ids else None

	frappe.enqueue(
		run_agent_job,
		queue="long",
		prompt=prompt,
		page_context=page_context,
		model=resolved_model,
		page_id=page_id,
		user=frappe.session.user,
		selected_component_ids=ids,
	)

	frappe.local.response.http_status_code = 202
	return {"status": "accepted"}
