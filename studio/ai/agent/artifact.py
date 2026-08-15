"""Artifact generators — produce a large streamed artifact for a tool.

An *artifact tool* (one that sets `artifact=` on its `Tool`) delegates its
execution to a generator here. The generator runs on the user's selected *heavy*
model and streams the artifact to the client as plain content — reliable, unlike
tool-call argument streaming, which providers buffer (the canvas would stay blank
for the whole completion). After streaming, it returns the canonical client op for
the loop to emit so the frontend applies the authoritative, fully-parsed result.

The agent calling the tool is the only trigger: when the fast conversational model
decides to build the page, it calls `generate_page(brief=…)` and the loop hands off
here. No DB status or out-of-band heuristic gates generation.
"""

import base64
import logging
import mimetypes
import re

import frappe
import requests

from studio.ai import llm
from studio.ai.agent.tools.introspect import describe_page_data
from studio.ai.block_codec import BlockCodec
from studio.ai.models import ModelRegistry
from studio.ai.prompts import GENERATION
from studio.ai.session import AISession
from studio.ai.urlguard import assert_not_private_url

logger = frappe.logger("studio.ai.agent.artifact")
logger.setLevel(logging.INFO)

IMAGE_MARKER_RE = re.compile(r"(?:REFERENCE|HERO) IMAGE:\s*(\S+)", re.IGNORECASE)
MAX_ATTACHED_IMAGES = 2
IMAGE_CHECK_TIMEOUT = 5


def generate_page_json(ctx, args: dict) -> list[dict]:
	"""Stream a complete page of block JSON on the heavy model, then return a
	`generate_page` client op carrying the authoritative parsed block tree.

	`ctx` is the AgentRunner. `args["brief"]` is the concise spec the conversational
	model assembled from the approved plan / conversation. Streams `kind="page_json"`
	chunks to the canvas as the model writes them. Returns [] if the model produced
	nothing.
	"""
	brief = (args.get("brief") or "").strip()

	messages: list[dict] = [
		{"role": "system", "content": GENERATION, "cache_control": {"type": "ephemeral"}},
	]
	# Prior conversation (incl. the approved plan) as proper role-tagged turns.
	messages.extend(AISession.build_context_messages_from_id(ctx.session_id))
	# The generator builds its own prompt, so it won't see data sources created earlier this
	# turn unless told — hand it the page's data state so it binds to real, existing sources.
	if data_note := _available_data_note(ctx):
		messages.append({"role": "user", "content": data_note})
	# Photos search_images found this turn — exact urls, so none get retyped wrong.
	if photos := found_photo_list(ctx):
		messages.append({"role": "user", "content": photos})
	messages.append(_build_message(ctx, brief))

	ctx.emit("progress", message="Building the page…")

	content = ""
	finish_reason = None
	stream = llm.complete(ctx.model, messages, llm.TASK_PARAMS["complex"], stream=True, api_key=ctx.api_key)
	for chunk in stream:
		if ctx.is_cancelled():
			try:
				stream.close()
			except Exception:
				pass
			from studio.ai.agent.loop import CancelledError

			raise CancelledError
		if not chunk.choices:
			continue
		if fr := chunk.choices[0].finish_reason:
			finish_reason = fr
		delta = chunk.choices[0].delta.content
		if delta:
			content += delta
			ctx.emit("stream", chunk=delta, kind="page_json")

	if finish_reason == "length":
		logger.warning("generate_page hit max_tokens — the page may be truncated")
	try:
		block = BlockCodec.parse_blocks(content)
	except Exception as e:
		logger.warning("generate_page_json: could not parse model output (model=%s): %s", ctx.model, e)
		return []

	return [{"tool_name": "generate_page", "args": {"block": block}}]


def _build_message(ctx, brief: str) -> dict:
	"""The final 'build' turn. When a screenshot is attached and the model can see it, send the
	image to the GENERATOR itself (not just the conversational model) so the block tree is produced
	from the actual pixels — far higher fidelity than reproducing the model's textual brief.
	REFERENCE/HERO IMAGE markers in the brief are attached too (probed first — an
	unreachable URL fails the whole completion)."""
	text = f"Build this page now:\n{brief}" if brief else "Build the page now."
	if not ModelRegistry.is_vision_capable(ctx.model):
		return {"role": "user", "content": text}
	parts: list[dict] = []
	if image_url := getattr(ctx, "image_url", None):
		text += (
			"\n\nReproduce the ATTACHED design faithfully: match its layout structure, section order, "
			"component choices, spacing, alignment, typography and colors (approximated with espresso "
			"tokens). The brief above is a summary — the image is the source of truth."
		)
		parts.append({"type": "image_url", "image_url": {"url": image_url}})
	parts.extend(brief_image_parts(brief))
	if not parts:
		return {"role": "user", "content": text}
	return {"role": "user", "content": [{"type": "text", "text": text}, *parts]}


def image_url_resolves(url: str) -> bool:
	"""Whether the provider will be able to fetch this image. An attached URL it
	cannot reach fails the ENTIRE completion — models retype URLs and transpose
	digits, so a cheap HEAD is worth it before betting the turn on one. Model-
	authored, so it gets the SSRF guard; redirects are left for the provider."""
	try:
		assert_not_private_url(url)
		r = requests.head(url, timeout=IMAGE_CHECK_TIMEOUT, allow_redirects=False)
		if r.status_code in (403, 405):  # some CDNs only answer GET
			r = requests.get(url, timeout=IMAGE_CHECK_TIMEOUT, stream=True, allow_redirects=False)
			r.close()
		return r.ok
	except Exception as e:
		logger.warning(f"brief image {url} unreachable: {e}")
		return False


def brief_image_parts(brief: str) -> list[dict]:
	"""Resolve the brief's image markers into message image parts. https URLs are
	attached directly (the provider fetches them); /files/ paths are read from the
	site and inlined as data URLs. The marker lines always stay in the brief text,
	so the model still knows the exact URLs to place in blocks."""
	parts = []
	for url in IMAGE_MARKER_RE.findall(brief or ""):
		if len(parts) >= MAX_ATTACHED_IMAGES:
			break
		if url.startswith("https://"):
			if not image_url_resolves(url):
				logger.warning(f"skipping unreachable brief image: {url}")
				continue
			parts.append({"type": "image_url", "image_url": {"url": url}})
		elif url.startswith("/files/"):
			if data_url := read_site_image(url):
				parts.append({"type": "image_url", "image_url": {"url": data_url}})
	return parts


def read_site_image(file_url: str) -> str | None:
	try:
		name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not name:
			return None
		content = frappe.get_doc("File", name).get_content()
		if isinstance(content, str):
			content = content.encode()
		mime = mimetypes.guess_type(file_url)[0] or "image/png"
		return f"data:{mime};base64,{base64.b64encode(content).decode()}"
	except Exception as e:
		logger.warning(f"could not inline site image {file_url}: {e}")
		return None


def found_photo_list(ctx) -> str:
	"""The turn's search_images results, as an inventory the generator can draw on.
	Every url here came back from a provider, so it resolves — unlike one the model
	retyped from memory. Copy them EXACTLY."""
	found = getattr(ctx, "found_images", None) or []
	if not found:
		return ""
	preamble = (
		"PHOTOS AVAILABLE for this page — real results already searched for you. Use these "
		"EXACT urls in image props (copy character for character, never retype or guess one). "
		"Unused ones are fine to ignore."
	)
	lines = [preamble]
	for i, p in enumerate(found, 1):
		desc = (p.get("description") or "").strip()[:100] or p.get("query") or "photo"
		lines.append(f"{i}. [{p.get('query')}] {desc} — {p.get('size')}\n   {p.get('url')}")
	return "\n".join(lines)


def _available_data_note(ctx) -> str:
	"""A message listing the data sources + variables already on the page, so the
	generator binds the layout to real, existing sources (per the DATA BINDING rules).
	Empty when the page has no data layer yet."""
	page_id = getattr(ctx, "target_page_id", None) or ctx.page_id
	page = frappe.get_doc("Studio Page", page_id) if page_id else None
	if page is None:
		return ""
	state = describe_page_data(page)
	if not state["data_sources"] and not state["variables"]:
		return ""
	return (
		"Data sources and variables already created on this page — bind the layout to THESE "
		"(and only these), per the DATA BINDING rules:\n" + BlockCodec.to_json(state)
	)
