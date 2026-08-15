---
name: studio-app-building
description: Build Frappe Studio apps and pages — the block JSON schema, data sources, bindings, page scripts (custom vs standard form), and app structure. Use when creating or editing Studio Page block trees, wiring Frappe data into Studio pages, writing Studio page scripts, or working on a Studio App from any coding agent.
---

# Building Frappe Studio apps

Studio is a visual app builder on the Frappe Framework. An app (`Studio App`) is a
set of pages (`Studio Page`); each page stores a **block tree** (JSON), optional
**data sources** (child table `Studio Page Resource`), and a **page script**.
frappe-ui components render the blocks (see the `frappe-ui` skill for the
component API and design tokens).

The runtime source of truth for the rules below is `studio/ai/prompts.py`
(BLOCK_SCHEMA, BUILD_RULES, BINDING_CONTRACT, SCRIPTING_RULES) — if this file
and that one disagree, prompts.py wins.

## Where things live

- Page blocks: `Studio Page.draft_blocks` (JSON array with one root block); published copy in `blocks`.
- The root block must be a `div`/`container` with `originalElement` set — blocks without it don't render.
- Data sources: rows in `Studio Page.resources` — Document List / Document / API Resource, with optional `transform`, `on_success`, `on_error` hooks and `auto` fetch.
- Page script: `Studio Page.script`.
- Standard (exported) apps additionally materialize as files under the linked Frappe app's `studio/` folder; a build step compiles them.

## Block JSON (compact schema)

A block is:

```json
{
  "name": "Button",              // component name, or "container"/"div"
  "originalElement": "div",     // required for container/div blocks
  "label": "Save button",       // optional human label
  "props": {"label": "Save", "variant": "solid"},
  "style": {"padding": "8px"},  // desktop CSS (camelCase keys)
  "mstyle": {}, "tstyle": {},   // mobile / tablet overrides
  "slots": {"prefix": {"slotContent": [ ... ]}},
  "events": {"click": "count += 1"},
  "visibility": "user.isLoggedIn",
  "c": [ ... ]                   // children (default slot)
}
```

Rules that bite:

- Two-way binds are stored as `{"$type": "variable", "name": "..."}` prop values.
- `{{ expression }}` works in props, styles, and visibility; event scripts are bare
  statements (no braces). Handler-props inside component props (a Dialog action's
  `onClick`, a Dropdown option's `onClick`) must be **arrow-function strings**:
  `"() => { ... }"` — unlike block events.
- Repeater children see `dataItem` and `dataIndex`.
- Use espresso design tokens (`var(--ink-...)`, `var(--surface-...)`) — never raw hex.

## Data sources

Create a Document List source per doctype you render; bind with
`{{ source_name.data }}`. Filters use the Frappe list-filter JSON format.
Point a Repeater at the source and give each child bindings via `dataItem`.
Never invent doctype or field names — read the real schema first
(`frappe.get_meta` / the agent's `get_doctype_fields` tool).

## Page scripts — two forms

- **Custom (non-exported) app**: a bare interpreted `<script setup>`-style body.
  Ambient context: variables and data sources are auto-exposed by name. No
  imports, no export.
- **Standard (exported) app**: an ES module — `export default function setup(context) { ... }`
  with explicit imports (incl. `@app/*`) and an explicit return of what the page
  uses. State lives in code (refs/stores), not Studio variables.

Never mix the forms: a module script on a custom page (or a bare script on a
standard page) is rejected.

## Working across an app

Keep sibling pages visually consistent: read an existing page's tree before
building a new one, reuse its palette, spacing rhythm and section structure.
Routes start with `/` and must be unique within the app. Build one page at a
time, completely, before starting the next.
