"""Runtime error feedback — the loop's ears to go with preview_page's eyes.

The Studio renderer (editor canvas and /dev preview alike) reports uncaught
errors and failed data-source calls to `studio.ai.api.report_page_error`; they
land in a short Redis ring per page. get_page_errors lets the agent read (and
clear) them, so "check for errors and fix them" is a tool call, not a guess.
Because preview_page loads the /dev preview in Chromium, errors thrown during
that load are captured here too — screenshot then errors is the natural pair.
"""

import json

import frappe

from studio.ai.agent.registry import Tool

MAX_ERRORS_PER_PAGE = 20
ERRORS_TTL = 3600


def errors_key(page_id: str) -> str:
	return f"studio_ai_page_errors:{page_id}"


def record_error(page_id: str, message: str, source: str = "", stack: str = "") -> None:
	entry = json.dumps(
		{"message": (message or "")[:500], "source": (source or "")[:200], "stack": (stack or "")[:1000]}
	)
	cache = frappe.cache()
	key = cache.make_key(errors_key(page_id))
	cache.rpush(key, entry)
	cache.ltrim(key, -MAX_ERRORS_PER_PAGE, -1)
	cache.expire(key, ERRORS_TTL)


def read_errors(page_id: str, clear: bool = True) -> list[dict]:
	cache = frappe.cache()
	key = cache.make_key(errors_key(page_id))
	raw = cache.lrange(key, 0, -1) or []
	if clear:
		cache.delete(key)
	out = []
	for item in raw:
		try:
			out.append(json.loads(item))
		except (json.JSONDecodeError, TypeError):
			continue
	return out


def run_get_page_errors(ctx, args: dict) -> str:
	from studio.ai.agent.tools.pages import resolve_page

	page_id = ctx.target_page_id or ctx.page_id
	if ref := (args.get("page_name") or "").strip():
		page_id = resolve_page(ctx, ref)
		if page_id.startswith("FAILED"):
			return page_id
	if not page_id:
		return "FAILED: no page in context."
	errors = read_errors(page_id)
	if not errors:
		return "No runtime errors recorded for this page."
	lines = [f"{len(errors)} runtime error(s) recorded (now cleared). Fix the causes:"]
	for e in errors:
		line = f"- {e.get('message')}"
		if e.get("source"):
			line += f" (at {e['source']})"
		lines.append(line)
		if e.get("stack"):
			lines.append(f"  stack: {e['stack'][:300]}")
	return "\n".join(lines)


TOOLS = [
	Tool(
		name="get_page_errors",
		side="server",
		handler=run_get_page_errors,
		description=(
			"Read (and clear) the runtime errors the page's renderer reported — uncaught "
			"exceptions and failed data-source calls. Check after building or when a preview "
			"screenshot shows blank areas; fix what it reports instead of guessing."
		),
		parameters={
			"type": "object",
			"properties": {
				"page_name": {
					"type": "string",
					"description": "The page to check. Defaults to the working page.",
				},
			},
		},
	)
]
