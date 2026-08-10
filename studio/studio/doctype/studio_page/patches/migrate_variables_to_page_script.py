import json
import re

import frappe

MARKER = "// Migrated from page variables."

TYPE_DEFAULTS = {"String": '""', "Number": "0", "Boolean": "false", "Object": "{}"}


def execute():
	"""Fold legacy `Studio Page Variable` rows into each page's `script` as `ref()` declarations.

	The doctype/table was retired in favour of page scripts: a variable and a top-level `ref` in the
	page script were already the same thing at runtime (both reached bindings unwrapped and handlers
	as refs), so the declarations below are behaviour-preserving.

	Only non-exported (interpreted) pages are migrated: exported pages run in code mode where the
	script lives in the on-disk `<page>.ts`. Those are reported to the error log instead, with the
	exact declarations to paste in."""
	if not frappe.db.table_exists("Studio Page Variable"):
		return

	for page_name, variables in _read_variables().items():
		_migrate_page(page_name, variables)

	frappe.delete_doc("DocType", "Studio Page Variable", ignore_missing=True, force=True)


def _read_variables() -> dict[str, list[frappe._dict]]:
	variable = frappe.qb.DocType("Studio Page Variable")
	rows = (
		frappe.qb.from_(variable)
		.select(variable.parent, variable.variable_name, variable.variable_type, variable.initial_value)
		.where(variable.parenttype == "Studio Page")
		.orderby(variable.parent)
		.orderby(variable.idx)
		.run(as_dict=True)
	)
	grouped: dict[str, list[frappe._dict]] = {}
	for row in rows:
		grouped.setdefault(row.parent, []).append(row)
	return grouped


def _migrate_page(page_name: str, variables: list[frappe._dict]) -> None:
	if not frappe.db.exists("Studio Page", page_name):
		return

	page = frappe.get_doc("Studio Page", page_name)
	if page.is_standard:
		_report_unmigrated(page, variables)
		return

	existing = page.script or ""
	if MARKER in existing:
		return  # already migrated

	declarations = [_declare(v) for v in variables if not _already_declared(existing, v.variable_name)]
	if not declarations:
		return

	generated = MARKER + "\n" + "\n".join(declarations)
	# Prepended, not appended: the rest of the script already reads these names.
	page.script = generated + "\n\n" + existing.lstrip() if existing.strip() else generated + "\n"
	page.save()


def _report_unmigrated(page, variables: list[frappe._dict]) -> None:
	"""An exported page's script is the on-disk `<page>.ts`, a real ES module whose setup() must both
	declare and RETURN each ref — surgery too fragile to automate, and the file is checked into the
	owning app's repo. So log exactly what to paste, and where."""
	declarations = "\n".join(f"  {_declare(v)}" for v in variables)
	names = ", ".join(v.variable_name for v in variables)
	frappe.log_error(
		title=f"Studio: port page variables for '{page.page_title or page.name}'",
		message=(
			f"Page {page.name} is exported, so its variables could not be migrated automatically.\n"
			f"Add these to setup() in {page.get_export_docname()}.ts, drop them from the `context` "
			f"destructure, and add them to the returned object:\n\n{declarations}\n\n  return {{ {names}, ... }}"
		),
		reference_doctype="Studio Page",
		reference_name=page.name,
	)


def _declare(variable: frappe._dict) -> str:
	return f"const {variable.variable_name} = ref({_initial_value(variable)})"


def _initial_value(variable: frappe._dict) -> str:
	"""The stored value is already a JS literal for every variable type (Number as a bare number,
	Boolean as true/false, String/Object as JSON), so it drops straight into `ref(...)`."""
	default = TYPE_DEFAULTS.get(variable.variable_type, '""')
	value = (variable.initial_value or "").strip()
	if not value:
		return default
	try:
		json.loads(value)
	except ValueError:
		return default
	return value


def _already_declared(script: str, name: str) -> bool:
	"""A page script may already declare the same name — redeclaring it would throw at page load."""
	return bool(re.search(rf"\b(?:const|let|var|function|class)\s+{re.escape(name)}\b", script))
