"""Visual verification — the agent's eyes.

The studio skill's rule: "a build that compiles and a route that 200s prove
nothing about what rendered — load the preview and LOOK." `view_page` renders a
page's draft at its `/dev/<app_route>/<page_route>` preview in headless Chromium
and hands the screenshot back to the model (the loop attaches it as an image on
the next user message), so the agent can catch what only eyes catch: unreadable
ink steps, blank icons, cramped spacing, broken layout.

Playwright is an OPTIONAL dependency (`pip install playwright && playwright
install chromium` in the bench env). Without it — or on a non-vision model —
the tool fails softly and the agent proceeds without visual verification.

The preview needs an authenticated session; a fresh sid is minted for the
requesting user (never reusing their browser session) and the browser context
carries it as the `sid` cookie.
"""

import base64

import frappe

from studio.ai.agent.registry import Tool
from studio.ai.agent.tools.page import NO_PAGE, PAGE_NAME_PROP, load_page
from studio.ai.models import ModelRegistry

_VIEWPORT = {"width": 1280, "height": 800}
_NAV_TIMEOUT_MS = 20_000
# Data sources fetch after mount; give them (and fonts) a beat before capturing.
_SETTLE_MS = 1_800
# Above this, a full-page PNG bloats the vision payload — fall back to the viewport.
_MAX_FULL_PAGE_BYTES = 1_500_000


def run_view_page(ctx, args: dict) -> str:
	if not ModelRegistry.is_vision_capable(ctx.model):
		return "FAILED: the current model cannot see images — skip visual verification this turn."
	try:
		from playwright.sync_api import sync_playwright  # noqa: F401
	except ImportError:
		return (
			"FAILED: visual verification is not available on this server (playwright not installed). "
			"Proceed without it."
		)
	page = load_page(ctx, args)
	if page is None:
		return f"FAILED: {NO_PAGE}"
	app_route = frappe.db.get_value("Studio App", page.studio_app, "route")
	if not app_route:
		return "FAILED: the app has no route yet."
	url = f"{frappe.utils.get_url()}/dev/{app_route}{page.route}"

	ctx.emit("progress", message=f"Looking at '{page.page_title}'…")
	try:
		png = _capture(url, _mint_sid(ctx.user))
	except Exception as e:
		frappe.log_error(f"view_page capture failed: {e}", "studio.ai view_page")
		return f"FAILED: could not render the preview at {url}. Proceed without visual verification."

	data_url = "data:image/png;base64," + base64.b64encode(png).decode()
	ctx.pending_images.append(
		{"url": data_url, "note": f"Rendered preview of '{page.page_title}' ({page.route})"}
	)
	return (
		f"Captured the rendered preview of '{page.page_title}' — it is attached as an image in the "
		"next message. Inspect it against the design language (ink roles, spacing, alignment, icons "
		"that actually painted, empty/loading states) before continuing. The preview shows the last "
		"SAVED draft; if it looks like a stale version, the editor may still be saving — try once more."
	)


def _capture(url: str, sid: str) -> bytes:
	"""Screenshot `url` in headless Chromium, authenticated via the sid cookie.
	Full-page when reasonably sized, else the viewport."""
	from playwright.sync_api import sync_playwright

	with sync_playwright() as p:
		browser = p.chromium.launch()
		try:
			context = browser.new_context(viewport=_VIEWPORT, device_scale_factor=1)
			context.add_cookies([{"name": "sid", "value": sid, "url": url}])
			tab = context.new_page()
			tab.goto(url, wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
			tab.wait_for_timeout(_SETTLE_MS)
			png = tab.screenshot(full_page=True)
			if len(png) > _MAX_FULL_PAGE_BYTES:
				png = tab.screenshot()
			return png
		finally:
			browser.close()


def _mint_sid(user: str) -> str:
	"""A fresh authenticated session for `user`, for the headless browser only.

	Session.__init__ falls back to frappe.request (absent in a worker) unless a sid
	is present in form_dict — seed "Guest" so it takes the form_dict branch and then
	generates a brand-new sid. It also swaps frappe.local.session; restore the
	worker's own session state after."""
	from frappe.sessions import Session

	full_name, user_type = frappe.db.get_value("User", user, ["full_name", "user_type"])
	saved_session = frappe.local.session
	frappe.form_dict["sid"] = "Guest"
	try:
		session = Session(user=user, resume=False, full_name=full_name, user_type=user_type)
	finally:
		frappe.form_dict.pop("sid", None)
		frappe.local.session = saved_session
	frappe.db.commit()  # the web worker serving the preview must see the new session
	return session.sid


view_page = Tool(
	name="view_page",
	side="server",
	handler=run_view_page,
	description=(
		"LOOK at a page as it actually renders: capture a screenshot of its live preview and receive "
		"it as an image. Call this after generate_page / build_app_page or any major visual change, "
		"then fix what only eyes catch — unreadable text (wrong ink step), icons that didn't paint, "
		"cramped or misaligned layout, a missing empty state. Also useful when the user reports "
		"something looks wrong. Verify at most twice per turn; if it FAILs, proceed without it."
	),
	parameters={
		"type": "object",
		"properties": {"page_name": PAGE_NAME_PROP},
	},
)

TOOLS = [view_page]
