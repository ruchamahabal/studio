"""One source of truth for what components exist and what API they carry.

Names come from the editor's own registration constants
(frontend/src/utils/constants.js) — the same arrays the component panel is
built from, so the AI can never disagree with the editor about what exists.

API facts merge two layers at read time:
- BASE: frontend/src/json_types/*/*.json — JSON Schemas generated from the
  component prop TYPES (tsToJSONGenerator), the same files the editor's props
  panel consumes. Authoritative names/types/enums/required, and the only
  source covering @framework/ui and Studio-native components.
- ENRICHMENT: component_api.json, distilled from frappe-ui's auto-generated
  *.api.md by `yarn sync-component-api` — adds what types can't carry: human
  descriptions, defaults, slots, emits (frappe-ui components only).

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
	"""Props/slots/emits for one component — the editor's type schema merged with
	the distilled frappe-ui docs — or None when neither source knows it."""
	schema = _schema_data().get(name)
	distilled = _api_data().get(name)
	if not schema or not distilled:
		return schema or distilled
	enrichment = {p["name"]: p for p in distilled.get("props", [])}
	props = []
	for prop in schema.get("props", []):
		extra = enrichment.get(prop["name"], {})
		props.append(
			{
				**prop,
				**({"description": extra["description"]} if extra.get("description") else {}),
				**({"default": extra["default"]} if extra.get("default") else {}),
			}
		)
	known = {p["name"] for p in props}
	props += [p for p in distilled.get("props", []) if p["name"] not in known]
	merged = {"props": props} if props else {}
	if slots := distilled.get("slots") or schema.get("slots"):
		merged["slots"] = slots
	if emits := distilled.get("emits"):
		merged["emits"] = emits
	return merged or None


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
	"""{component: {props, slots?}} from the editor's generated prop-type schemas
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
		required = set(props_def.get("required") or [])
		props = [
			{"name": prop, "type": _schema_type(spec), **({"required": True} if prop in required else {})}
			for prop, spec in (props_def.get("properties") or {}).items()
		]
		if props:
			out[name] = {"props": props}
		slots_def = definitions.get(f"{name}Slots") or {}
		if isinstance(slots_def, dict) and slots_def.get("properties"):
			out.setdefault(name, {})["slots"] = [{"name": s} for s in slots_def["properties"]]
	return out


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
def _api_data() -> dict:
	return _load_json("studio/ai/component_api.json")


@lru_cache(maxsize=1)
def _family_data() -> dict:
	return _load_json("studio/ai/family_templates.json")


def _load_json(relative: str) -> dict:
	try:
		return json.loads(_read_repo_file(relative))
	except (OSError, json.JSONDecodeError):
		return {}


def _read_repo_file(relative: str) -> str:
	path = Path(__file__).resolve().parents[2] / relative
	try:
		return path.read_text(encoding="utf-8")
	except OSError:
		return ""
