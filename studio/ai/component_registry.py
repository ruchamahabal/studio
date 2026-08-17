"""One source of truth for what components exist and what API they carry.

Names come from the editor's own registration constants
(frontend/src/utils/constants.js) — the same arrays the component panel is
built from, so the AI can never disagree with the editor about what exists.

API facts come from frontend/src/json_types/*/*.json — JSON Schemas generated
from the component types (tsToJSONGenerator with jsDoc carried through), the
same files the editor's props panel consumes. One `<Component>.json` holds
`<Name>Props` (names/types/enums/required + JSDoc descriptions and defaults)
and, when the source exports them, `<Name>Slots` / `<Name>Emits`.

Consumers: the prompt appendix for registered-but-uncataloged components
(computed here, so the prompt can't drift from the registry) and the
list_components / describe_component agent tools.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

GROUPS = {
	"FRAPPE_UI_COMPONENTS": "frappe-ui",
	"FRAPPE_UI_MOLECULES": "frappe-ui list family",
	"FRAMEWORK_UI_COMPONENTS": "@framework/ui",
	"STUDIO_COMPONENTS": "studio",
}
CATALOG_LINE_RE = re.compile(r"^- ([A-Za-z]+)[:\s]", re.MULTILINE)


def registered_components() -> dict[str, list[str]]:
	"""{group label: [component names]} parsed from the editor's constants."""
	text = _read_repo_file("frontend/src/utils/constants.js")
	groups = {}
	for const, label in GROUPS.items():
		match = re.search(rf"export const {const} = \[(.*?)\]", text, re.DOTALL)
		names = re.findall(r'"([^"]+)"', match.group(1)) if match else []
		if names:
			groups[label] = names
	return groups


def component_api(name: str) -> dict | None:
	"""Props/slots/emits for one component (from the editor's type schemas), or
	None when no schema ships for it."""
	return _schema_data().get(name)


# The rule the editor's column manager enforces — every scaffold consumer repeats it.
LIST_COLUMNS_RULE = (
	"A List column lives in THREE places kept in step positionally: a track in the List's "
	"'columns' prop, a ListHeaderCell, and a ListCell in every row template — add/remove/reorder "
	"all three together. Bind ListRows 'items' to a data source ({{ source.data }}); inside the "
	"row template use {{ item.<field> }} and {{ value }} (the row identity)."
)


def family_scaffold(name: str) -> tuple[dict | None, str | None]:
	"""The editor's canonical composition for a family component (familyTemplates.ts,
	distilled to the compact schema) — (scaffold, family key), or (None, None)."""
	data = _family_data()
	kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
	if kebab in data:
		return data[kebab], kebab
	for prefix, family in (("list", "list"), ("settings", "settings-dialog"), ("sidebar", "sidebar")):
		if kebab.startswith(prefix) and family in data:
			return data[family], family
	return None, None


def catalog_names(catalog_text: str) -> set[str]:
	"""Component names documented in the prompt's curated catalog (its '- Name:' lines)."""
	return set(CATALOG_LINE_RE.findall(catalog_text))


def uncataloged_appendix(catalog_text: str) -> str:
	"""A compact, COMPUTED prompt block for every registered component the curated
	catalog doesn't document — prop names from the distilled API where available.
	Regenerates at import, so new registrations can never silently go missing."""
	known = {n.lower() for n in catalog_names(catalog_text)}
	lines = [
		"ALSO REGISTERED (usable, but less documented than the catalog above — reach for these "
		"only when the request names them or no catalog component fits; stick to the props "
		"listed, and treat entries with no props listed as risky):"
	]
	for label, names in registered_components().items():
		entries = [_appendix_entry(n) for n in names if n.lower() not in known]
		if entries:
			lines.append(f"{label}: " + "; ".join(entries))
	if len(lines) == 1:
		return ""
	# Lists are ubiquitous, so the List family's canonical composition rides the
	# prompt itself — the same structure the editor inserts (familyTemplates.ts).
	scaffold, _ = family_scaffold("List")
	if scaffold:
		lines.append(
			"\nList family — canonical composition (the editor inserts exactly this; copy the "
			f"structure, swap the content). {LIST_COLUMNS_RULE}\n{json.dumps(scaffold, separators=(',', ':'))}"
		)
	return "\n".join(lines)


def _appendix_entry(name: str) -> str:
	api = component_api(name)
	if not api or not api.get("props"):
		return name
	props = ", ".join(p["name"] for p in api["props"][:10])
	slots = [s["name"] for s in api.get("slots", []) if s["name"] != "default"]
	suffix = f" | slots: {', '.join(slots[:6])}" if slots else ""
	return f"{name} ({props}{suffix})"


@lru_cache(maxsize=1)
def _schema_data() -> dict:
	"""{component: {props, slots?, emits?}} from the editor's generated type schemas
	(frontend/src/json_types/<library>/<Component>.json)."""
	root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "json_types"
	out: dict[str, dict] = {}
	for file in sorted(root.glob("*/*.json")):
		try:
			definitions = json.loads(file.read_text(encoding="utf-8")).get("definitions") or {}
		except (OSError, json.JSONDecodeError):
			continue
		name = file.stem
		props_def = definitions.get(f"{name}Props") or next(
			(v for k, v in definitions.items() if k.endswith("Props")), None
		)
		if not isinstance(props_def, dict):
			continue
		if props := _definition_rows(props_def, with_types=True):
			out[name] = {"props": props}
		for kind in ("Slots", "Emits"):
			definition = definitions.get(f"{name}{kind}")
			if isinstance(definition, dict) and definition.get("properties"):
				out.setdefault(name, {})[kind.lower()] = _definition_rows(definition, with_types=False)
	return out


def _definition_rows(definition: dict, *, with_types: bool) -> list[dict]:
	required = set(definition.get("required") or [])
	rows = []
	for name, spec in (definition.get("properties") or {}).items():
		spec = spec if isinstance(spec, dict) else {}
		row = {"name": name}
		if with_types:
			row["type"] = _schema_type(spec)
		if name in required and with_types:
			row["required"] = True
		if isinstance(spec.get("description"), str):
			row["description"] = spec["description"]
		if spec.get("default") is not None:
			row["default"] = (
				json.dumps(spec["default"]) if not isinstance(spec["default"], str) else spec["default"]
			)
		rows.append(row)
	return rows


def _schema_type(spec: dict) -> str:
	if "enum" in spec:
		return " | ".join(str(v) for v in spec["enum"])
	if "$ref" in spec:
		return spec["$ref"].rsplit("/", 1)[-1]
	kind = spec.get("type")
	if isinstance(kind, list):
		return " | ".join(kind)
	if kind == "array":
		items = spec.get("items")
		return f"{_schema_type(items)}[]" if isinstance(items, dict) else "array"
	return kind or ("object" if spec.get("properties") else "any")


@lru_cache(maxsize=1)
def _family_data() -> dict:
	try:
		return json.loads(_read_repo_file("studio/ai/family_templates.json"))
	except (OSError, json.JSONDecodeError):
		return {}


def _read_repo_file(relative: str) -> str:
	path = Path(__file__).resolve().parents[2] / relative
	try:
		return path.read_text(encoding="utf-8")
	except OSError:
		return ""
