"""preview_page — let the agent SEE the page it built.

Studio pages are client-rendered Vue, so the capture drives Frappe's in-process
headless Chromium at the app's /dev preview URL with a short-lived session
minted for the requesting user (drafts need auth), waits for the SPA to paint,
then trims and tiles the screenshot into readable screenfuls for the vision
model. Degrades to a plain "preview unavailable" tool result when Chromium
isn't reachable — a missing renderer must never fail the turn.
"""

import base64
import logging

import frappe

from studio.ai.agent.registry import Tool

logger = frappe.logger("studio.ai.agent.preview")
logger.setLevel(logging.INFO)

MAX_PREVIEWS_PER_TURN = 2  # hard cost bound — a screenshot loop can't run away
MAX_IMAGE_BYTES = 3 * 1024 * 1024  # mirrors BlockCodec.validate_image_data's cap
PREVIEW_WIDTH = 1280
# The viewport we capture into. Chromium screenshots the viewport, not the
# document, so this has to clear a whole generated page. Blank tail is trimmed.
CAPTURE_HEIGHT = 8000
# One attached image per this many pixels of page. NOT one tall image: a vision
# model shrinks an image to fit its longest edge (~1568px), so a single
# 1280x6000 capture reaches the model with every label illegible.
TILE_HEIGHT = 2000
MAX_TILES = 3
SPA_RENDER_WAIT_MS = 3000

# How far a pixel may drift from the background before it counts as content —
# lossy webp leaves a couple of levels of drift across a blank band.
BLANK_TOLERANCE = 16


def run_preview_page(ctx, args: dict) -> str:
	from studio.ai.agent.tools.pages import resolve_page
	from studio.ai.models import ModelRegistry

	page_id = ctx.target_page_id or ctx.page_id
	if ref := (args.get("page_name") or "").strip():
		page_id = resolve_page(ctx, ref)
		if page_id.startswith("FAILED"):
			return page_id
	if not page_id:
		return "FAILED: no page in context — open or create a page first."
	if ctx.preview_count >= MAX_PREVIEWS_PER_TURN:
		return "Preview limit reached for this turn — proceed with what you have."
	ctx.preview_count += 1
	page = frappe.get_doc("Studio Page", page_id)
	try:
		image = capture_page(ctx, page)
	except Exception:
		logger.warning("preview_page: render failed for %s", page_id, exc_info=True)
		return (
			"Preview unavailable (screenshot renderer not reachable). "
			"Continue without the visual check — do not retry."
		)
	if not ModelRegistry.is_vision_capable(ctx.model):
		return "Your selected model can't view images — skip the visual check and continue."
	attached, complete = attach_to_model(ctx, page, image)
	if not attached:
		return "Screenshot captured but too large to attach for review — finish up."
	extent = (
		f"The page is attached below as {attached} images, top to bottom — review ALL of them."
		if attached > 1
		else "Screenshot attached below."
	)
	if not complete:
		extent += " They stop before the end of the page; anything past that you have NOT seen."
	# A screenshot of ANOTHER page is a reference to study, not a build to review.
	if page_id != (ctx.target_page_id or ctx.page_id):
		return (
			f"{extent} This is another page of the app, attached as a visual REFERENCE for "
			"your eyes only. Study its design language — palette, typography, spacing rhythm, "
			"section structure — and carry it into your work on the working page."
		)
	return (
		f"{extent} For YOUR eyes only (the user doesn't see it). Review in two passes, then act:\n"
		"1. BREAKAGE: unreadable contrast, accidental overlap, empty sections, components that "
		"didn't render (blank areas where content should be), a layout that clearly collapses.\n"
		"2. QUALITY — yes/no checks: (a) is there a clear visual hierarchy (one dominant "
		"element per section)? (b) are sections structurally distinct, not one centered column "
		"repeated? (c) is spacing consistent (a rhythm, not random gaps)? (d) do bound data "
		"areas show real content, not raw {{ }} expressions or empty lists? (e) does the page "
		"match what was asked for?\n"
		"Fix failures with surgical edits on the specific blocks (update_block / update_blocks) "
		"when the page is open in the editor, or a corrected generate_page otherwise. Don't "
		"describe the screenshot to the user."
	)


def capture_page(ctx, page) -> bytes:
	"""Screenshot the page's /dev draft preview as the requesting user."""
	from frappe.utils.preview import capture_screenshot

	url = preview_url(ctx, page)
	sid = mint_preview_sid(ctx.user)
	try:
		return capture_screenshot(
			"webp",
			url=url,
			headers={"Cookie": f"sid={sid}"} if sid else None,
			wait_for=SPA_RENDER_WAIT_MS,
			width=PREVIEW_WIDTH,
			height=CAPTURE_HEIGHT,
		)
	finally:
		drop_preview_sid(sid)


def preview_url(ctx, page) -> str:
	app_route = frappe.db.get_value("Studio App", page.studio_app or ctx.app_id, "route") or ""
	page_route = page.route or ""
	return frappe.utils.get_url(f"/dev/{app_route}{page_route}")


def mint_preview_sid(user: str) -> str | None:
	"""A short-lived real session for the capture (drafts need auth). Seeding
	form_dict['sid'] keeps Session() off frappe.request, which a worker lacks."""
	from frappe.sessions import Session

	try:
		frappe.form_dict["sid"] = "Guest"
		info = frappe.db.get_value("User", user, ["full_name", "user_type"], as_dict=True)
		session = Session(user=user, resume=False, full_name=info.full_name, user_type=info.user_type)
		return session.data.get("sid")
	except Exception:
		logger.warning("preview_page: could not mint a session, capturing unauthenticated", exc_info=True)
		return None
	finally:
		frappe.form_dict.pop("sid", None)


def drop_preview_sid(sid: str | None) -> None:
	if not sid:
		return
	try:
		from frappe.sessions import delete_session

		delete_session(sid, reason="Studio AI preview done")
	except Exception:
		pass


def content_height(im) -> int:
	"""Where the page actually ends — everything below is the blank tail of an
	oversized viewport. A whole-image diff against the trailing background colour."""
	from PIL import Image, ImageChops

	background = Image.new("RGB", im.size, im.getpixel((im.width // 2, im.height - 1)))
	drift = ImageChops.difference(im, background).convert("L")
	bbox = drift.point(lambda level: 255 if level > BLANK_TOLERANCE else 0).getbbox()
	return bbox[3] if bbox else im.height


def tile_screenshot(image: bytes) -> tuple[list[bytes], bool]:
	"""Trim the blank tail, then slice the page into readable screenfuls.
	Returns (tiles, complete) — complete is False when the page ran past MAX_TILES."""
	from io import BytesIO

	from PIL import Image

	im = Image.open(BytesIO(image)).convert("RGB")
	im = im.crop((0, 0, im.width, max(content_height(im), 1)))
	tiles = []
	for top in range(0, im.height, TILE_HEIGHT):
		buffer = BytesIO()
		im.crop((0, top, im.width, min(top + TILE_HEIGHT, im.height))).save(buffer, "WEBP", quality=80)
		tiles.append(buffer.getvalue())
		if len(tiles) == MAX_TILES:
			break
	return tiles, len(tiles) * TILE_HEIGHT >= im.height


def attach_to_model(ctx, page, image: bytes) -> tuple[int, bool]:
	"""Attach the page as a run of readable screenfuls, top to bottom. Returns
	(tiles attached, whether they cover the whole page)."""
	try:
		tiles, complete = tile_screenshot(image)
	except Exception:
		logger.warning("preview_page: tiling failed, attaching the raw capture", exc_info=True)
		tiles, complete = [image], True
	title = page.page_title or page.name
	attached = 0
	for index, tile in enumerate(tiles, start=1):
		if len(tile) > MAX_IMAGE_BYTES:
			continue
		where = f" — part {index} of {len(tiles)}, top to bottom" if len(tiles) > 1 else ""
		ctx.pending_images.append(
			{
				"caption": f"Screenshot of draft page '{title}'{where}:",
				"data_url": "data:image/webp;base64," + base64.b64encode(tile).decode(),
			}
		)
		attached += 1
	return attached, complete and attached == len(tiles)


TOOLS = [
	Tool(
		name="preview_page",
		side="server",
		handler=run_preview_page,
		description=(
			"Render a page's draft to a screenshot attached to you so you can SEE what you "
			"built (the user is not shown the image in chat). Call it after EVERY "
			"generate_page build: it returns a review rubric (breakage + quality checks); "
			"fix failures with surgical block edits, optionally preview once more, never "
			"loop screenshots. Also works on ANOTHER page (pass page_name) to study it as a "
			"visual reference before building a page that must match it. If the renderer is "
			"unavailable, continue without it."
		),
		parameters={
			"type": "object",
			"properties": {
				"page_name": {
					"type": "string",
					"description": "The page to screenshot. Defaults to the working page.",
				},
			},
		},
	)
]
