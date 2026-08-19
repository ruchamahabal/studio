---
name: studio-app-building
description: Build Frappe Studio apps and pages — the block JSON schema, data sources, bindings, page scripts (custom vs standard form), the design language, and app structure. Use when creating or editing Studio Page block trees, wiring Frappe data into Studio pages, writing Studio page scripts, deciding how a Studio page should look, or working on a Studio App from any coding agent.
---

# Building Frappe Studio apps

Studio is a visual app builder on the Frappe Framework. An app (`Studio App`) is
a set of pages (`Studio Page`); each page stores a **block tree** (JSON),
optional **data sources** (child table `Studio Page Resource`), and a **page
script**. frappe-ui components render the blocks (the `frappe-ui` skill in
`frappe-ui/skills/` covers the component API for hand-written Vue).

The runtime source of truth for the rules below is `studio/ai/prompts.py`
(BLOCK_SCHEMA, STYLING_RULES, COMPONENT_CATALOG, …) — if this file and that one
disagree, prompts.py wins. How pages should LOOK lives in
[DESIGN.md](DESIGN.md) — read it before building or restyling any page (it is
baked into the runtime AI prompts from this directory).

## Where things live

- Page blocks: `Studio Page.draft_blocks` (JSON array with ONE root block);
  the published copy is in `blocks`.
- The root block (and every `container`/`div` block) must carry
  `originalElement` (`"body"` for the root, `"div"` for containers) — blocks
  without it render nothing, all the way down. Never put `originalElement` on
  a component block.
- Data sources: rows in `Studio Page.resources` — Document List / Document /
  API Resource, with optional `transform`, `on_success`, `on_error` hooks.
- Page script: `Studio Page.script`.
- Standard (exported) apps additionally materialize as files under the linked
  Frappe app; editing those files on disk syncs back to the DB on dev setups.

## Block JSON

Stored blocks use the full keys: `componentName`, `componentProps`,
`baseStyles` / `mobileStyles` / `tabletStyles` (camelCase CSS), `componentSlots`,
`children`, `componentEvents`, `visibilityCondition`, `blockName`, and a
`componentId` unique in the tree. Studio's AI tools speak a compact alias form
(`name`/`props`/`style`/`mstyle`/`tstyle`/`slots`/`c`/`events`/`visibility`/`label`);
the shapes are otherwise identical.

Rules that bite:

- Two-way binds are stored as `{"$type": "variable", "name": "..."}` prop
  values, resolved against page-script state.
- `{{ expression }}` works in props, styles, and visibility. Block event
  scripts are bare statements (no braces); the runtime exposes `$event` (the
  event's first argument, as in Vue) and calls a `handleEvent(...args)`
  function if the script defines one. Event-name modifiers
  (`dragover.prevent`, `keydown.enter`) are preferred over manual
  preventDefault/stopPropagation.
- Handler props living INSIDE component props — a Dialog action's `onClick`, a
  Dropdown/ContextMenu option's `onClick` — must be **arrow-function
  strings**: `"() => { ... }"`. The component calls the value directly, so a
  bare statement string throws. This differs from block events.
- Repeater children see `dataItem` (current row) and `dataIndex`.
- Keep `{{ }}` bindings THIN — property access plus at most one short
  ternary. Real computation (date math, pluralization, chained ternaries, any
  IIFE) belongs in the page script as a named helper the binding calls:
  `{{ formatDueDate(dataItem.exp_end_date) }}`, with `formatDueDate` declared
  in the script (custom: top-level function, auto-exposed; standard: returned
  from `setup()`). An inline IIFE in a prop is unreadable, undebuggable, and
  re-evaluated on every render of every Repeater row.
- Use espresso tokens (`var(--ink-...)`, `var(--surface-...)`,
  `var(--outline-...)`) — never raw hex. Full styling judgment: [DESIGN.md](DESIGN.md).

## Data sources

Create a Document List source per doctype you render; bind with
`{{ source_name.data }}` (a single Document exposes `{{ source_name.doc }}`).
Filters use Frappe's list-filter JSON: `{"status": "Open"}` or
`{"status": ["!=", "Closed"]}`; multiple values need `["in", [...]]` — a bare
value list crashes the fetch. Point a Repeater at the source and bind its
child blocks via `dataItem`. Never invent doctype or field names — read the
real schema first (`frappe.get_meta`, or the agent's schema tools).

## Page scripts — two forms

- **Custom (non-exported) app**: a bare interpreted script body. Ambient
  context: variables and data sources are auto-exposed by name (variables are
  refs — write via `.value`). No imports, no export.
- **Standard (exported) app**: an ES module —
  `export default function setup(context) { ... }` with explicit imports and
  an explicit return of what the page uses. State lives in code (refs,
  stores), not Studio variables.

Never mix the forms: a module script on a custom page (or a bare script on a
standard page) is rejected.

## Working across an app

Keep sibling pages visually consistent: read an existing page's tree before
building a new one and reuse its palette, spacing rhythm, and section
structure. Routes start with `/` and are unique within the app. Build one
page at a time, completely, before starting the next; wire navigation on the
page that links to a new page, not just the new page itself.
