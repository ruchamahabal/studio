"""The Frappe design language, distilled for Studio AI generation.

Source of truth: the frappe-ui skill bundled in this repo
(frappe-ui/skills/frappe-ui — DESIGN.md, TOKENS.md, COMPONENTS.md), which
captures how Gameplan / CRM / Helpdesk / Drive / Insights are designed. That
skill speaks Vue + Tailwind classes; Studio blocks are styled with camelCase
style props and espresso CSS variables, so this module carries the TRANSLATED
digest both prompts embed. The full skill files stay readable at runtime via
the read_ui_skill tool for depth the digest leaves out.

Plain strings (NOT f-strings) so any `{{ }}` examples survive verbatim.
"""

DESIGN_LANGUAGE = """# Design language (the quality bar — distilled from the frappe-ui skill)
Every page must look like a Frappe product (Gameplan, CRM, Helpdesk, Drive, Insights). When unsure, read the full skill with read_ui_skill('frappe-ui/DESIGN').

PRINCIPLES
- GRAY FIRST. Ink-gray text on var(--surface-base); color appears ONLY where it encodes information (status, severity, sign, unread). The primary Button is variant "solid" with the default gray theme. At most ONE accent per screen.
- HIERARCHY THROUGH INK, NOT BOXES. Build structure with the ink ladder + type scale and thin dividers (borderColor var(--outline-gray-1)) — not nested bordered cards. A border must earn its place: an interactive affordance, an overlay, or a genuinely distinct surface.
- ONE PRIMARY ACTION per screen, in the page header; every other button "subtle" or "ghost".
- DENSE BUT BREATHABLE. 13–14px body text, 40–60px list rows, 48px page header, generous bottom padding (40px+) at the end of scrollable content.
- ALIGNMENT OVER FLOW. Repeating trailing elements (badges, timestamps, counts) get fixed-width columns so rows line up — not ragged flex ends.
- ICONS SUPPORT LABELS, never replace them. Icon-only buttons only for universal actions (close, overflow "…"). No decorative icons sprinkled around.
- SENTENCE CASE EVERYWHERE. Never uppercase headings/labels and never letter-space to fake all-caps ("Recent activity", not "RECENT ACTIVITY"). A quiet section label is fontSize text-sm + color var(--ink-gray-5), not capitals.

INK LADDER — pick text color by ROLE, not by eye:
- var(--ink-gray-9): page default, strongest values (unread titles, KPI figures)
- var(--ink-gray-8): titles, headings, primary content
- var(--ink-gray-7): secondary values, table cells, descriptions
- var(--ink-gray-6): field labels, form icons
- var(--ink-gray-5): timestamps, counts, captions, meta, quiet section labels
- var(--ink-gray-4): ids, decorative glyphs
SURFACES: var(--surface-base) page; var(--surface-gray-1)/(--surface-gray-2) subtle fills and hover; var(--surface-elevation-1) raised cards; var(--surface-sidebar) sidebars. BORDERS: var(--outline-gray-1)/(--outline-gray-2) default hairlines.

TYPE BY ROLE (TextBlock fontSize):
- Page title text-2xl (18px) or text-3xl (20px), fontWeight 600, ink-gray-8/9. text-4xl+ is hero/marketing only.
- Section heading text-lg, fontWeight 600, ink-gray-8.
- Row/card title text-base; meta line below it text-sm, ink-gray-5, marginTop ~6px.
- Paragraphs/descriptions/helper text: the text-p-* scale (text-p-sm / text-p-base), ink-gray-7. Single-line labels use tight text-*; multi-line copy uses text-p-* — never the reverse.

GEOMETRY (px values in style props):
- Page header: minHeight 48px, borderColor var(--outline-gray-1) bottom hairline, title left / primary action right.
- Sidebar 224px wide; nav rows ~28px tall, 2px gaps.
- Gutters: padding 12px (compact) to 20px on header AND body so content aligns; page body starts with paddingTop 20–24px and scroll content ends with paddingBottom 40px+.
- Content width: reading pages maxWidth 940px centered; prose/forms maxWidth 640–770px; dashboards maxWidth 896px; dense tables may run full-width.
- Stacks: sections gap 24px; form fields gap 16px; inline action clusters gap 8px; list rows separated by hairline dividers, not gaps.
- borderRadius: 8px (0.5rem) inputs/buttons/list items, 10px cards, 12px dialogs. Full-bleed sections get none.

COLOR = MEANING. When state must be shown: Badge with variant "subtle" and a theme from ONE lookup — e.g. open→blue, done/success→green, error/overdue→red, pending→orange, closed/draft→gray. Status dots are 8px circles (borderRadius 9999px) with backgroundColor var(--surface-blue-7)-style tokens. Positive/negative numbers: var(--ink-green-6)/var(--ink-red-6). Everything not encoding state stays gray.

SCREEN ARCHETYPES (compose from the catalog):
- List page: header (title + count + solid Button) → toolbar (search TextInput + filter controls) → ListView (tabular, 40–48px rows) or Repeater with a row-template container (h ~56–60px, hairline divider, title + meta + fixed-width trailing meta).
- Detail page: Breadcrumbs → title row with actions → content column plus optional right meta panel (width 320px, borderColor var(--outline-gray-1) left hairline, label/value rows with ink-gray-6 labels).
- Form: single column, maxWidth ~640px, FormControl per field (label + placeholder, never placeholder-as-label), fields gap 16px, footer right-aligned: ghost/subtle Cancel then solid submit.
- Dashboard: centered maxWidth 896px; KPI strip of NumberCharts separated by hairline dividers (not boxed cards); charts below in sections gap 24px.
- App frame: Sidebar (app name header, nav items with lucide icons, counts right-aligned ink-gray-5) + main column (page header + scrollable body).
- Empty state: centered column, gap 12px, paddingTop/Bottom 64px: a 40px circle (surface-gray-2) holding a FeatherIcon (e.g. "inbox") colored ink-gray-5, then "No <things> yet" text-base ink-gray-7, a one-line hint text-sm ink-gray-5, and the primary action Button. Show it via visibility {{ <source>.data.length === 0 }} alongside the list's inverse.
- Loading/feedback: bind Button loading states where supported; toast.success after writes, toast.error on failure; destructive confirmation = a red-theme Dialog whose confirm action is solid red — never delete silently."""


# Appended to the read_ui_skill tool result for frappe-ui docs: the skill speaks
# Tailwind classes; Studio blocks take style props + CSS variables.
SKILL_TRANSLATION_NOTE = """NOTE — translating this skill to Studio blocks:
The skill's Vue/Tailwind classes map onto Studio's style props:
- bg-surface-X → style backgroundColor: "var(--surface-X)"; text-ink-X → color: "var(--ink-X)"; border-outline-X → borderColor: "var(--outline-X)" (+ borderWidth "1px", borderStyle "solid").
- Spacing/size classes → px values (p-4 → padding "16px"; space-y-4 → a column container with gap "16px"; h-12 → height "48px"; w-56 → width "224px"; max-w-xl → maxWidth "576px"; size-4 icon → 16px).
- rounded → borderRadius "0.5rem"; rounded-md → "0.625rem"; rounded-lg → "0.75rem"; rounded-full → "9999px".
- text-<size> classes → the TextBlock fontSize prop (same names, incl. text-p-*); font weights → style fontWeight.
- v-model on an input → props {"modelValue":{"$type":"variable","name":"<name>"}}; `useCall`/`useList` → Studio data sources (add_data_source) or `call()` in scripts; imperative dialog.confirm → a Dialog block with red-theme confirm action; toast.* works as-is in scripts.
- Components the Studio catalog doesn't list (DesktopShell, List family, ScrollArea, Editor, HoverCard…) are NOT available as blocks — compose the same look from container/Sidebar/ListView/Repeater per the catalog. Use this skill for DESIGN decisions (hierarchy, tokens, geometry, patterns), and the catalog for what you may instantiate."""
