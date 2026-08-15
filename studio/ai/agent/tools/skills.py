"""read_skill — pull a skill's full documentation into the conversation."""

from studio.ai.agent.registry import Tool


def run_read_skill(ctx, args: dict) -> str:
	from studio.ai import skills

	name = (args.get("name") or "").strip()
	if not name:
		return "FAILED: pass the skill name (see <available_skills> in your instructions)."
	return skills.read(name, (args.get("file") or "").strip() or None)


TOOLS = [
	Tool(
		name="read_skill",
		side="server",
		handler=run_read_skill,
		description=(
			"Read a skill's documentation — SKILL.md by default, or one of its reference "
			"files (e.g. read_skill('frappe-ui', file='COMPONENTS.md') for the full component "
			"API, or file='TOKENS.md' for the design tokens). Read the relevant file BEFORE "
			"building UI that leans on knowledge you're unsure of; don't guess props."
		),
		parameters={
			"type": "object",
			"properties": {
				"name": {"type": "string", "description": "Skill name from <available_skills>."},
				"file": {
					"type": "string",
					"description": "Optional reference file within the skill, e.g. COMPONENTS.md.",
				},
			},
			"required": ["name"],
		},
	)
]
