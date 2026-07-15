# Repeater UX Problems

An audit of the current Repeater component's usability issues in Studio.

**Relevant files:**
- [`Repeater.vue`](../frontend/src/components/AppLayout/Repeater.vue) — the runtime component
- [`Repeater.ts`](../frontend/src/types/studio_components/Repeater.ts) — props type (`data`, `dataKey`, `emptyStateMessage`)
- [`ComponentContextMenu.vue`](../frontend/src/components/ComponentContextMenu.vue) — the "Repeat Block" creation flow
- [`components.ts`](../frontend/src/data/components.ts) — component registration

## Root cause

The Repeater is a **fixed-layout, string-configured runtime primitive**, but it's being used as a **design-time visual container**. Most problems below fall out of that mismatch.

## Known problems (already flagged)

1. **Empty state is uncustomizable.** It's a single `emptyStateMessage` string. No styling, illustration, layout, or dynamic binding. **Decision:** a customizable `empty` slot was tried but reverted as over-engineered (it needed a preview toggle + overlay machinery to be editable). Current behavior: the empty state is just `emptyStateMessage`, and it renders **only when the message is set** — no more forced "No data" default. Richer empty states are out of scope for now.
2. ~~**No repeater indicator.** Nothing in the tree/canvas signals "this block is a repeater" or "these children are a repeated template."~~ **DONE** — the canvas label and tree now show a repeat icon on the Repeater block, and its direct children (the repeated template) carry a repeat badge in both the canvas label and the layers tree. Backed by a new `Block.isRepeated()` helper.
3. **Built-in empty state fights a custom one.** The template uses `v-if`/`v-else`, so a block dropped into the slot renders *per data item*, never as the empty state. **Moot for now** — since we dropped the custom `empty` slot (see #1) and the built-in message only renders when set, there's nothing to conflict with. Re-opens if a customizable empty state is revisited.

## Additional problems

4. ~~**Container layout is hardcoded.** `flex flex-row flex-wrap gap-5` is baked into the template (`Repeater.vue:2`). In a visual builder you can't set direction, gap, wrap, alignment, or use a grid. Likely the single biggest limitation.~~ **DONE** — the layout is now expressed as the block's default `baseStyles` (`display:flex; flex-direction:row; flex-wrap:wrap; gap:20px`), merged *under* saved styles in the Block constructor. So the Styles panel shows Display + the full Flex layout section (and Grid), and existing repeaters get backfilled with the identical layout without clobbering customizations. **Migration note:** the backfill reads `Block.components`, which is only set in the editor (`main.ts`), not the app renderer (`renderer.ts`). So the original Tailwind classes are kept on the div as a fallback for already-*published* pages (whose saved `baseStyles` are empty); inline styles override them wherever present (editor + pages saved after this change), so the panel stays the effective source of truth.
5. **No loading state.** While the data resource is fetching, the repeater shows the "No data" message — loading and truly-empty are indistinguishable.
6. **No error / non-array state.** If the data source fails or returns a non-array, it silently falls through to the empty message with no feedback.
7. **`dataKey` is a fragile, required free-text field.** No dropdown/autocomplete from the data shape (`Repeater.ts:3`). `:key="dataItem?.[dataKey] || dataIndex"` (`Repeater.vue:9`) silently falls back to the index when the key is wrong or falsy (`0`, `""`), causing subtle re-render/state bugs.
8. **No design-time preview.** With no bound data, the canvas shows nothing (or just the message, if set), so there's nothing to design the item template against.
9. **The "Repeat Block" creation flow is rough.** It wraps the block, then fires `toast.warning("Please set data & data key…")` (`ComponentContextMenu.vue:113`) instead of guiding the user to a config panel.
10. **Single "default" slot only.** No separate roles for empty / header / footer / separator — which is precisely why problem #3 exists.
11. **Template-vs-instance editing is ambiguous.** Children are authored once but rendered N times; it's unclear which rendered instance is "the source" or how selection/editing maps back to the template. Repeater context only exists at runtime.

## Suggested prioritization

- **Done:** #2 (indicator), #4 (layout → styles)
- **High impact:** #5/#6 (loading/error states)
- **Correctness:** #7 (`dataKey` fallback bug)
- **Discoverability:** #9 (creation flow), #8 (preview)
- **Structural:** #10 (slots), #11 (template/instance model)
- **Parked:** #1/#3 (custom empty state — intentionally kept simple: message-only, shown when set)
