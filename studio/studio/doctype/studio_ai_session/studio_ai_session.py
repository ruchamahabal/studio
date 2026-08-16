# Copyright (c) 2026, Frappe Technologies Pvt Ltd and contributors
# For license information, please see license.txt
import frappe
from frappe.model.document import Document


class StudioAISession(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		is_running: DF.Check
		last_interaction_on: DF.Datetime | None
		last_task_type: DF.Data | None
		page: DF.Link
		selected_model: DF.Data | None
		user: DF.Link
	# end: auto-generated types

	def on_trash(self):
		# Messages and revert snapshots exist only for their session — plain row
		# deletes (neither doctype has controller logic to run).
		frappe.db.delete("Studio AI Message", {"session": self.name})
		frappe.db.delete("Studio AI Snapshot", {"session": self.name})
