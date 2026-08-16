import { defineComponent, h, markRaw, type Component } from "vue"
// @vue/shared ships with vue itself — these are the same tag lists the template compiler uses
import { isHTMLTag, isSVGTag, isMathMLTag, isVoidTag } from "@vue/shared"

// Blocks whose componentName is a known native tag render as plain DOM elements.
// Registered component names are PascalCase (Vue style guide), so a lowercase
// known tag can never shadow a component.
function isNativeTag(tag: string) {
	return isHTMLTag(tag) || isSVGTag(tag) || isMathMLTag(tag)
}

const NATIVE_TEXT_TAGS = new Set([
	"p", "span", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code", "blockquote", "a", "button",
	"label", "li", "strong", "em", "b", "i", "small", "cite", "figcaption", "td", "th", "option",
])

function isNativeTextTag(tag: string) {
	return NATIVE_TEXT_TAGS.has(tag)
}

const elementCache = new Map<string, Component>()

// <component :is="'button'"> resolves strings against the component registry with a
// capitalize fallback ("button" → frappe-ui Button), so native tags must bypass string
// resolution: h() with a string always creates a real element vnode.
function getNativeElementComponent(tag: string): Component {
	let component = elementCache.get(tag)
	if (!component) {
		component = markRaw(
			defineComponent({
				name: `native-${tag}`,
				inheritAttrs: false,
				setup(_, { attrs, slots }) {
					return () => {
						const { textContent, ...rest } = attrs
						if (isVoidTag(tag)) return h(tag, rest)
						// child blocks win over the textContent prop
						return h(tag, rest, slots.default ? slots.default() : (textContent as string | undefined))
					}
				},
			}),
		)
		elementCache.set(tag, component)
	}
	return component
}

// Editor-canvas-only attributes so interactive elements don't act while editing.
// Plain clicks are already intercepted by the canvas selection handler.
function getEditorSafetyAttributes(tag: string): Record<string, any> {
	if (tag === "input" || tag === "textarea") return { readonly: true }
	if (tag === "select") return { onMousedown: (e: Event) => e.preventDefault() }
	if (tag === "form") return { onSubmit: (e: Event) => e.preventDefault() }
	return {}
}

// curated options for the Tag switcher; any other valid tag can be typed in
const TAG_OPTIONS = [
	"div", "section", "article", "aside", "nav", "header", "footer", "main",
	"h1", "h2", "h3", "h4", "h5", "h6", "p", "span", "pre", "code", "blockquote",
	"ul", "ol", "li", "a", "button", "label", "form", "input", "textarea", "select", "option",
	"img", "video", "audio", "iframe", "canvas", "hr",
	"table", "thead", "tbody", "tr", "th", "td", "figure", "figcaption",
]

export {
	isNativeTag,
	isNativeTextTag,
	isVoidTag,
	getNativeElementComponent,
	getEditorSafetyAttributes,
	TAG_OPTIONS,
}
