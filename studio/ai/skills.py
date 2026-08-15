"""Skills — packaged knowledge the agent reads on demand.

Follows the `.agents/skills/<name>/SKILL.md` convention (YAML frontmatter with
name + description), so the same skill files serve three consumers: this
runtime agent, Claude Code, and Codex-style CLIs working on the repo. Two
roots ship with Studio: the repo's own `.agents/skills/` and the frappe-ui
submodule's `skills/`. The prompt carries only a compact index; bodies and
reference files are fetched through the read_skill tool, jailed to the skill's
own directory.
"""

import os
import re
from pathlib import Path

import frappe

MAX_SKILL_BYTES = 256 * 1024
MAX_SKILLS = 50
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def skill_roots() -> list[Path]:
	app_root = Path(frappe.get_app_path("studio")).parent
	return [app_root / ".agents" / "skills", app_root / "frappe-ui" / "skills"]


def discover() -> list[dict]:
	"""Every valid skill: {name, description, path}. Cheap enough to run per
	turn (a handful of stat calls); invalid entries are skipped silently."""
	skills = []
	for root in skill_roots():
		if not root.is_dir():
			continue
		for entry in sorted(root.iterdir()):
			manifest = entry / "SKILL.md"
			if len(skills) >= MAX_SKILLS or not manifest.is_file():
				continue
			meta = parse_frontmatter(manifest)
			if not meta:
				continue
			name = meta.get("name") or entry.name
			if name != entry.name or not NAME_RE.match(name):
				continue
			if not meta.get("description"):
				continue
			skills.append({"name": name, "description": meta["description"], "path": entry})
	return skills


def index_for_prompt() -> str:
	"""The <available_skills> block for the system prompt — names and one-line
	descriptions only; the model pulls a body with read_skill when relevant."""
	skills = discover()
	if not skills:
		return ""
	lines = ["<available_skills>"]
	lines.append(
		"Deeper reference docs you can read with the read_skill tool when the task touches their topic:"
	)
	for s in skills:
		files = ", ".join(reference_files(s["path"]))
		extra = f" (files: {files})" if files else ""
		lines.append(f"- {s['name']}: {s['description']}{extra}")
	lines.append("</available_skills>")
	return "\n".join(lines)


def read(name: str, file: str | None = None) -> str:
	"""A skill's SKILL.md, or one of its reference files. Jailed to the skill's
	directory (realpath containment) and size-capped."""
	skill = next((s for s in discover() if s["name"] == name), None)
	if not skill:
		known = ", ".join(s["name"] for s in discover()) or "none"
		return f"FAILED: no skill named '{name}'. Available: {known}."
	target = skill["path"] / (file or "SKILL.md")
	root = os.path.realpath(skill["path"])
	resolved = os.path.realpath(target)
	if not resolved.startswith(root + os.sep) and resolved != root:
		return "FAILED: that path is outside the skill."
	if not target.is_file():
		files = ", ".join(reference_files(skill["path"])) or "SKILL.md"
		return f"FAILED: no file '{file}' in skill '{name}'. Available: {files}."
	if target.stat().st_size > MAX_SKILL_BYTES:
		return f"FAILED: {file or 'SKILL.md'} is too large to read."
	return target.read_text(errors="replace")


def reference_files(path: Path) -> list[str]:
	return sorted(f.name for f in path.iterdir() if f.is_file() and f.suffix == ".md")


def parse_frontmatter(manifest: Path) -> dict | None:
	try:
		if manifest.stat().st_size > MAX_SKILL_BYTES:
			return None
		text = manifest.read_text(errors="replace")
	except OSError:
		return None
	match = FRONTMATTER_RE.match(text)
	if not match:
		return None
	meta = {}
	for line in match.group(1).splitlines():
		if ":" not in line:
			continue
		key, _, value = line.partition(":")
		meta[key.strip()] = value.strip()
	return meta
