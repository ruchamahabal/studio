import json

import frappe
import litellm

COMPONENT_CATALOG = """
LAYOUT:
- container: layout wrapper (renders as a div). No componentProps. Use baseStyles: display, flexDirection, gap, padding, width, height, flexWrap, alignItems, justifyContent, flexShrink, flex, etc.

TEXT & DISPLAY:
- TextBlock: {text: "string", tag: "p|h1|h2|h3|h4|h5|h6|span"}
- Badge: {variant: "subtle|solid|outline", theme: "green|red|orange|blue|gray", size: "sm|md|lg", label: "string"}
- Avatar: {shape: "circle|square", size: "xs|sm|md|lg|xl|2xl|3xl", label: "initials", image: "url"}
- Progress: {value: 0-100, size: "sm|md|lg", label: "string"}
- Alert: {title: "string", description: "string", theme: "yellow|red|green|blue"}
- ErrorMessage: {message: "string"}
- FeatherIcon: {name: "feather-icon-name", class: "h-5 w-5"}
- ImageView: {image: "url", size: "xs|sm|md|lg|xl"}
- Divider: (no props)
- Tooltip: {text: "string"}
- HTML: {html: "<p>raw html</p>"}

INPUTS:
- TextInput: {placeholder: "string"}
- Textarea: {placeholder: "string"}
- FormControl: {type: "text|email|number|select|date|autocomplete|password", label: "string", placeholder: "string"}
- Select: {placeholder: "string", options: [{label: "string", value: "string"}]}
- Checkbox: {label: "string", checked: true|false}
- Switch: {label: "string", description: "string", modelValue: true|false}
- DatePicker: {placeholder: "string"}
- TimePicker: {placeholder: "string"}
- DateTimePicker: {placeholder: "string"}
- MultiSelect: {placeholder: "string", options: [{label: "string", value: "string"}]}
- Rating: {label: "string"}
- FileUploader: {label: "string", fileTypes: "['image/*']"}
- TextEditor: {modelValue: "string", editable: true, fixedMenu: true}

ACTIONS:
- Button: {label: "string", variant: "solid|subtle|outline|ghost", size: "sm|md|lg|xl|2xl", theme: "gray (DEFAULT — omit unless red/green/blue is semantically required)"}
- Dropdown: {options: [{label: "string", icon: "feather-icon"}], button: {label: "string"}}

NAVIGATION:
- Breadcrumbs: {items: [{label: "string", route: "string"}]}
- Tabs: {tabs: [{label: "string"}]}
- TabButtons: {buttons: [{label: "string", value: "string"}]}
- Sidebar: {header: {title: "string", subtitle: "string"}, sections: [{label: "string", items: [{label: "string", icon: "string", to: "string"}]}]}

DATA DISPLAY:
- ListView: {columns: [{label: "string", key: "string", width: number}], rows: [{key: value}], rowKey: "string"}
- NumberChart: {config: {title: "string", value: number, prefix: "string", delta: number}}
- AxisChart: {config: {data: [{xKey: val, yKey: val}], xAxis: {key: "string", type: "time|category"}, yAxis: {title: "string"}, series: [{name: "string", type: "bar|line"}]}}
- DonutChart: {config: {data: [{cat: val, val: number}], categoryColumn: "string", valueColumn: "string"}}
- Filter: {doctype: "string", filters: {}}
- Link: {doctype: "string"}
- Tree: {nodeKey: "string", node: {name: "string", label: "string", children: []}}
- Repeater: (no props — repeats child template over data)
- Calendar: {config: {defaultMode: "Month"}, events: []}

AUTOCOMPLETE:
- Autocomplete: {placeholder: "string", options: [{label: "string", value: "string"}]}
- Combobox: {placeholder: "string", options: [{group: "string", options: [{label, value}]}]}
"""

SYSTEM_PROMPT = f"""You are an expert UI builder for Frappe Studio, a Vue.js-based low-code app builder. Your task is to generate a JSON block tree that Studio will render as a live Vue application. Each block in the tree maps to a Vue component or native html element (div) or a Studio Vue component or a Frappe UI Vue component.

OUTPUT FORMAT:
Return ONLY a JSON object with a single key "blocks" containing an array with one root block.

BLOCK STRUCTURE:
{{
  "componentName": "string (required)",
  "componentProps": {{}},      // component-specific props
  "baseStyles": {{}},          // CSS-in-JS camelCase properties
  "children": [],              // nested blocks (for container blocks)
  "componentSlots": {{}}       // for frappe-ui components that hold child content
}}

ROOT BLOCK:
Always start with: {{"componentName": "div", "originalElement": "body", "blockName": "body", "baseStyles": {{"display": "flex", "flexDirection": "column", "flexShrink": 0, "width": "inherit", "overflowX": "hidden", "height": "100%"}}}}

LAYOUT CONTAINERS (CRITICAL — originalElement is required or children won't render):
{{"componentName": "container", "originalElement": "div", "blockName": "container", "baseStyles": {{}}, "children": [...]}}
- Use container for all inner layout wrappers — never use "div" as componentName for inner blocks
- flexDirection: "row" for horizontal layouts, "column" for vertical
- Use gap, padding for spacing. width: "100%" for full-width sections. flex: 1 to fill space.

COMPONENT STYLING RULES:
- Always use CSS variables. Avoid raw hex colors/values.
\t- backgroundColor:  var(--surface-white) | var(--surface-gray-1..7) | var(--surface-cards) | var(--surface-red-1) | var(--surface-green-1) | var(--surface-amber-1) | var(--surface-blue-1)
\t- color (text): var(--ink-white) | var(--ink-gray-1..9)
\t- borderColor: var(--outline-white) | var(--outline-gray-1..5) | var(--outline-red-1..3) | var(--outline-green-1..2) | var(--outline-amber-1..2) | var(--outline-blue-1) | var(--outline-orange-1)
\t- boxShadow: "sm" | "DEFAULT" | "md" | "lg" | "xl" | "2xl" | "none" (keywords only, not raw values)
\t- borderRadius: "none" (0px) | "sm" (0.25rem) | "DEFAULT" (0.5rem) | "md" (0.625rem) | "lg" (0.75rem) | "xl" (1rem) | "2xl" (1.25rem) | "full" (9999px)
- Button: use size prop ("sm"|"md"|"lg"|"xl"|"2xl") for sizing — DO NOT set height in baseStyles. Keep `theme` gray or default unless prompted. Only use colored themes (blue, red, green) when semantically meaningful: destructive actions → red, success/confirmed → green.
- Avoid applying visual baseStyles (color, backgroundColor, border, fontSize) to frappe-ui components (eg: height on Button component) — their props handle this. Only use baseStyles on components for layout (width, flex, margin, etc.).
- TextBlock: use tag prop for semantics (h1/h2/h3 for headings, p for body). Set fontSize/fontWeight/color on TextBlock baseStyles.

AVAILABLE COMPONENTS:
{COMPONENT_CATALOG}

RULES:
- componentName must exactly match a name from the catalog above
- baseStyles keys must be camelCase CSS (backgroundColor, borderRadius, fontSize, etc.)
- Do NOT include componentId (auto-generated)
- Do NOT include parentBlock
- Keep componentProps to only what's relevant to the description

EXAMPLE — "A login form with email, password and a submit button":
{{
  "blocks": [{{
    "componentName": "div", "originalElement": "body", "blockName": "body",
    "baseStyles": {{"display": "flex", "flexDirection": "column", "flexShrink": 0, "width": "inherit", "overflowX": "hidden", "height": "100%"}},
    "children": [{{
      "componentName": "container", "originalElement": "div", "blockName": "container",
      "baseStyles": {{"display": "flex", "flexDirection": "column", "alignItems": "center", "justifyContent": "center", "flex": 1, "padding": "24px"}},
      "children": [{{
        "componentName": "container", "originalElement": "div", "blockName": "container",
        "baseStyles": {{"display": "flex", "flexDirection": "column", "gap": "16px", "width": "100%", "maxWidth": "400px", "padding": "32px", "backgroundColor": "var(--surface-white)", "borderRadius": "0.75rem", "boxShadow": "md"}},
        "children": [
          {{"componentName": "TextBlock", "componentProps": {{"text": "Sign In", "tag": "h2"}}, "baseStyles": {{"fontSize": "20px", "fontWeight": "600", "color": "var(--ink-gray-9)"}}, "children": []}},
          {{"componentName": "TextInput", "componentProps": {{"placeholder": "Email address"}}, "children": []}},
          {{"componentName": "FormControl", "componentProps": {{"type": "password", "label": "Password", "placeholder": "Enter password"}}, "children": []}},
          {{"componentName": "Button", "componentProps": {{"label": "Sign In", "variant": "solid"}}, "children": []}}
        ]
      }}]
    }}]
  }}]
}}
"""


ADD_BLOCK_TOOL = {
	"type": "function",
	"function": {
		"name": "add_block",
		"description": (
			"Add a single UI block to the page. Call once per block in depth-first order "
			"(parent before children). Do NOT include a 'children' key in the block data."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"temp_id": {
					"type": "string",
					"description": "Unique ID for this block, e.g. 'b0', 'b1', 'b2', ...",
				},
				"parent_temp_id": {
					"type": "string",
					"description": "temp_id of the parent block. Omit only for the root block.",
				},
				"block": {
					"type": "object",
					"description": "Block definition without 'children'.",
					"properties": {
						"componentName": {"type": "string"},
						"originalElement": {"type": "string"},
						"blockName": {"type": "string"},
						"componentProps": {"type": "object"},
						"baseStyles": {"type": "object"},
						"componentSlots": {"type": "object"},
					},
					"required": ["componentName"],
				},
			},
			"required": ["temp_id", "block"],
		},
	},
}

TOOL_SYSTEM_PROMPT = f"""You are an expert UI builder for Frappe Studio. Build the requested page by calling the add_block tool once per block, in depth-first order (parent before children).

BLOCK FIELDS (no "children" key):
- componentName: required
- originalElement: required for container/body blocks ("div" for both)
- blockName: descriptive name ("body", "container", "header", etc.)
- componentProps: component-specific props
- baseStyles: camelCase CSS properties
- componentSlots: for frappe-ui slot content

TEMP IDS: Assign sequential IDs "b0", "b1", "b2", ... Set parent_temp_id to the parent's temp_id (omit only for root).

ROOT BLOCK (always first — temp_id "b0", no parent_temp_id):
componentName: "div", originalElement: "body", blockName: "body"
baseStyles: {{"display": "flex", "flexDirection": "column", "flexShrink": 0, "width": "inherit", "overflowX": "hidden", "height": "100%"}}

LAYOUT CONTAINERS (all inner wrappers):
componentName: "container", originalElement: "div", blockName: "container"
- flexDirection: "row" (horizontal) or "column" (vertical)
- gap/padding for spacing; width: "100%" for full-width; flex: 1 to fill
- Never use "div" for inner blocks

STYLING (always CSS variables, never hex):
- backgroundColor: var(--surface-white) | var(--surface-gray-1..7) | var(--surface-cards) | var(--surface-red-1) | var(--surface-green-1) | var(--surface-amber-1) | var(--surface-blue-1)
- color: var(--ink-white) | var(--ink-gray-1..9)
- borderColor: var(--outline-gray-1..5) | var(--outline-red-1..3) | var(--outline-green-1..2)
- boxShadow: "sm" | "DEFAULT" | "md" | "lg" | "xl" | "none"
- borderRadius: "none" | "sm" | "DEFAULT" | "md" | "lg" | "xl" | "2xl" | "full"
- Button: size prop only, no height in baseStyles; theme gray by default
- TextBlock: tag prop for semantics; fontSize/fontWeight/color in baseStyles
- No visual baseStyles on frappe-ui components — layout only (width, flex, margin)

AVAILABLE COMPONENTS:
{COMPONENT_CATALOG}

RULES:
- componentName must exactly match a catalog entry
- baseStyles keys must be camelCase CSS
- No componentId, no parentBlock, no children in block data
- Depth-first order: b0 → first child of b0 → its first child → ... → last sibling
"""


def _get_llm_config() -> tuple[str, str]:
	settings = frappe.get_single("Studio Settings")
	api_key = settings.get_password("openrouter_api_key") if settings.openrouter_api_key else None
	model = settings.ai_model or "openrouter/google/gemini-2.5-flash-preview"
	if not api_key:
		frappe.throw("OpenRouter API key is not configured. Please set it in Studio Settings.")
	return model, api_key


@frappe.whitelist()
def generate_page_from_prompt(prompt: str) -> str:
	"""Non-streaming: returns full block JSON immediately."""
	model, api_key = _get_llm_config()

	response = litellm.completion(
		model=model,
		messages=[
			{"role": "system", "content": SYSTEM_PROMPT},
			{"role": "user", "content": prompt},
		],
		api_key=api_key,
	)

	content = response.choices[0].message.content
	if not content:
		frappe.throw("The AI model returned an empty response. Try a different model or prompt.")

	content = _strip_fences(content)
	try:
		parsed = json.loads(content)
	except json.JSONDecodeError as e:
		frappe.log_error(title="Studio AI: JSON parse error", message=f"{e}\ncontent:\n{content}")
		frappe.throw(f"The AI model returned invalid JSON ({e}). Raw response has been logged.")

	blocks = parsed.get("blocks", parsed) if isinstance(parsed, dict) else parsed
	if not isinstance(blocks, list):
		frappe.throw("AI returned an unexpected response format. Please try again.")

	return json.dumps(blocks)


@frappe.whitelist()
def generate_page_streaming(prompt: str, job_id: str) -> dict:
	frappe.enqueue(
		"studio.studio.ai._run_streaming_generation",
		queue="short",
		timeout=120,
		prompt=prompt,
		generation_id=job_id,
		user=frappe.session.user,
		enqueue_after_commit=True,
	)
	return {"status": "queued", "job_id": job_id}


def _run_streaming_generation(prompt: str, generation_id: str, user: str) -> None:
	def emit(event: str, **kwargs):
		frappe.publish_realtime(
			f"studio_ai_{event}",
			{"job_id": generation_id, **kwargs},
			user=user,
		)

	def flush_tool_call(tc_data: dict, idx: int) -> bool:
		try:
			args = json.loads(tc_data["arguments"])
			block = args.get("block", {})
			temp_id = args.get("temp_id", f"b{idx}")
			parent_temp_id = args.get("parent_temp_id") or None
			emit(
				"block",
				block=block,
				temp_id=temp_id,
				parent_temp_id=parent_temp_id,
				is_root=not parent_temp_id,
			)
			return True
		except (json.JSONDecodeError, KeyError):
			return False

	try:
		model, api_key = _get_llm_config()

		response = litellm.completion(
			model=model,
			messages=[
				{"role": "system", "content": TOOL_SYSTEM_PROMPT},
				{"role": "user", "content": prompt},
			],
			api_key=api_key,
			tools=[ADD_BLOCK_TOOL],
			tool_choice="required",
			stream=True,
		)

		pending: dict[int, dict] = {}
		emitted: set[int] = set()
		max_seen = -1
		count = 0

		for chunk in response:
			choice = chunk.choices[0]
			for tc in choice.delta.tool_calls or []:
				idx = tc.index
				if idx not in pending:
					pending[idx] = {"arguments": ""}
					for prev in range(max_seen + 1, idx):
						if prev in pending and prev not in emitted:
							if flush_tool_call(pending[prev], prev):
								count += 1
							emitted.add(prev)
					max_seen = max(max_seen, idx)
				if tc.function:
					if tc.function.name and "name" not in pending[idx]:
						pending[idx]["name"] = tc.function.name
					if tc.function.arguments:
						pending[idx]["arguments"] += tc.function.arguments

			if choice.finish_reason in ("tool_calls", "stop", "end_turn"):
				for i in sorted(k for k in pending if k not in emitted):
					if flush_tool_call(pending[i], i):
						count += 1
					emitted.add(i)
				break

		emit("complete", total=count)

	except Exception as e:
		frappe.log_error(title="Studio AI: Generation error", message=str(e))
		emit("error", message=str(e))


def _strip_fences(text: str) -> str:
	text = text.strip()
	if text.startswith("```"):
		lines = text.splitlines()
		inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
		return "\n".join(inner).strip()
	return text
