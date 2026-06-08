// Classifies a template tag as a native Studio block or a custom Vue component.
// Reuses Studio's authoritative component-name lists (constants.js) instead of
// duplicating them, so the importer stays in sync with what Studio can render.

import {
	FRAPPE_UI_COMPONENTS,
	FRAPPE_COMPONENTS,
	STUDIO_COMPONENTS,
} from "../utils/constants.js"

// Names Studio renders natively (frappe-ui + frappe + studio built-ins).
export const NATIVE_COMPONENT_NAMES = new Set<string>([
	...FRAPPE_UI_COMPONENTS,
	...FRAPPE_COMPONENTS,
	...STUDIO_COMPONENTS,
	"Container",
	"Header",
])

export type TagKind = "native" | "html" | "custom"

// ElementTypes from @vue/compiler-core: ELEMENT=0, COMPONENT=1, SLOT=2, TEMPLATE=3
export function classifyTag(tag: string, elementType: number): TagKind {
	if (elementType === 0) return "html"
	if (NATIVE_COMPONENT_NAMES.has(tag)) return "native"
	return "custom"
}

export function isContainerHtmlTag(tag: string): boolean {
	return tag === "div" || tag === "header"
}
