"""Sessions were page-scoped; they are now app-scoped (the page survives as focus
context). Fill `app` from each session's page, title untitled rows from their
first prompt, and mark everything Active."""

import frappe


def execute():
	for row in frappe.get_all("Studio AI Session", fields=["name", "page"]):
		updates = {"status": "Active"}
		if row.page:
			app = frappe.db.get_value("Studio Page", row.page, "studio_app")
			if app:
				updates["app"] = app
		if title := first_prompt(row.name):
			updates["title"] = title
		frappe.db.set_value("Studio AI Session", row.name, updates, update_modified=False)


def first_prompt(session: str) -> str | None:
	prompt = frappe.db.get_value(
		"Studio AI Message",
		{"session": session, "role": "user"},
		"content",
		order_by="creation asc",
	)
	return prompt[:60].strip() if prompt else None
