"""Skill tools — let the agent read the bundled UI/design skills at full depth.

The studio repo bundles the frappe-ui skill (frappe-ui/skills/frappe-ui:
component catalog, design tokens, the app design language) and Studio's own
authoring skill (skills/studio). The prompts embed a distilled digest
(design_language.py); these tools serve the complete documents when the agent
needs more — an unfamiliar screen archetype, exact token steps, a component's
usage contract. frappe-ui docs get a translation note appended, because the
skill speaks Vue + Tailwind while blocks are styled with props + CSS variables.
"""

import os

import frappe

from studio.ai.agent.registry import Tool
from studio.ai.agent.tools.page import text_arg
from studio.ai.design_language import SKILL_TRANSLATION_NOTE

_SKILL_SUMMARIES = {
	"frappe-ui/SKILL": "frappe-ui overview: the core rules (component-first, semantic tokens, variant+theme color).",
	"frappe-ui/DESIGN": "The app design language: principles, screen archetypes, ink ladder, geometry, color rules, form/empty/loading patterns. Read before designing a whole app or an unfamiliar screen.",
	"frappe-ui/TOKENS": "Design tokens in full: every ink/surface/outline step, both type scales, radius and shadow ladders, dark mode.",
	"frappe-ui/COMPONENTS": "Component-by-component usage: when to reach for each, key props, pitfalls.",
	"studio/SKILL": "Studio authoring rules: block JSON contracts, script forms, repeater scope, icon gotchas.",
}


def run_list_ui_skills(ctx, args: dict) -> str:
	lines = [f"- {name}: {summary}" for name, summary in _SKILL_SUMMARIES.items() if _skill_path(name)]
	if not lines:
		return "No skill documents found in this installation."
	return "UI/design skill documents (read one with read_ui_skill):\n" + "\n".join(lines)


def run_read_ui_skill(ctx, args: dict) -> str:
	name = text_arg(args.get("skill"))
	path = _skill_path(name)
	if path is None:
		available = ", ".join(k for k in _SKILL_SUMMARIES if _skill_path(k))
		return f"FAILED: unknown skill '{name}'. Available: {available}."
	content = frappe.read_file(path)
	if not content:
		return f"FAILED: could not read skill '{name}'."
	note = f"\n\n{SKILL_TRANSLATION_NOTE}" if name.startswith("frappe-ui/") else ""
	return f"Skill {name}:\n{content}{note}"


def _skill_path(name: str) -> str | None:
	"""Absolute path of a known skill doc, or None. Only names from _SKILL_SUMMARIES
	resolve — the model can't use this to read arbitrary files."""
	if name not in _SKILL_SUMMARIES:
		return None
	repo_root = os.path.dirname(os.path.normpath(frappe.get_app_path("studio")))
	folder, stem = name.split("/", 1)
	subdir = (
		os.path.join("frappe-ui", "skills", "frappe-ui")
		if folder == "frappe-ui"
		else os.path.join("skills", "studio")
	)
	path = os.path.join(repo_root, subdir, f"{stem}.md")
	return path if os.path.isfile(path) else None


list_ui_skills = Tool(
	name="list_ui_skills",
	side="server",
	handler=run_list_ui_skills,
	description=(
		"List the bundled frappe-ui design/UI skill documents and Studio's authoring skill. Each is a "
		"full reference readable with read_ui_skill."
	),
	parameters={"type": "object", "properties": {}},
)

read_ui_skill = Tool(
	name="read_ui_skill",
	side="server",
	handler=run_read_ui_skill,
	description=(
		"Read one of the bundled UI/design skill documents in full. Use when the design-language "
		"digest in your instructions isn't enough: 'frappe-ui/DESIGN' before designing a whole app or "
		"an unfamiliar screen archetype, 'frappe-ui/TOKENS' for exact token steps and type scales, "
		"'frappe-ui/COMPONENTS' for a component's detailed usage. frappe-ui docs come with a note on "
		"translating their Tailwind classes to Studio style props."
	),
	parameters={
		"type": "object",
		"properties": {
			"skill": {
				"type": "string",
				"description": "Document id, e.g. 'frappe-ui/DESIGN', 'frappe-ui/TOKENS', 'frappe-ui/COMPONENTS'.",
			}
		},
		"required": ["skill"],
	},
)

TOOLS = [list_ui_skills, read_ui_skill]
