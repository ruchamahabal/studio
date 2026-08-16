import { isNativeTextTag } from "@/utils/nativeElements"
import type { ComponentProps, FrappeUIComponents } from "@/types"

import LucideLayoutPanelTop from "~icons/lucide/layout-panel-top"
import LucidePilcrow from "~icons/lucide/pilcrow"
import LucideType from "~icons/lucide/type"
import LucideCode from "~icons/lucide/code"
import LucideMousePointerClick from "~icons/lucide/mouse-pointer-click"
import LucideLink from "~icons/lucide/link"
import LucideTextCursorInput from "~icons/lucide/text-cursor-input"
import LucideLetterText from "~icons/lucide/letter-text"
import LucideChevronsUpDown from "~icons/lucide/chevrons-up-down"
import LucideImage from "~icons/lucide/image"
import LucideClipboardList from "~icons/lucide/clipboard-list"

// Palette entries for native HTML elements. Each drops a styled preset (blockTemplate),
// never a bare zero-size tag. The long tail of tags is reachable via the Tag switcher.
export const NATIVE_ELEMENTS: FrappeUIComponents = {
	section: {
		name: "section",
		title: "Section",
		icon: LucideLayoutPanelTop,
		blockTemplate: "section",
	},
	p: {
		name: "p",
		title: "Paragraph",
		icon: LucidePilcrow,
		blockTemplate: "p",
		initialState: { textContent: "Paragraph text" },
	},
	span: {
		name: "span",
		title: "Span",
		icon: LucideType,
		blockTemplate: "span",
		initialState: { textContent: "Span" },
	},
	pre: {
		name: "pre",
		title: "Preformatted",
		icon: LucideCode,
		blockTemplate: "pre",
		initialState: { textContent: "Preformatted text" },
	},
	button: {
		name: "button",
		title: "Button",
		icon: LucideMousePointerClick,
		blockTemplate: "button",
		initialState: { type: "button", textContent: "Button" },
	},
	a: {
		name: "a",
		title: "Link",
		icon: LucideLink,
		blockTemplate: "a",
		initialState: { href: "#", textContent: "Link" },
	},
	input: {
		name: "input",
		title: "Input",
		icon: LucideTextCursorInput,
		blockTemplate: "input",
		initialState: { type: "text", placeholder: "Input" },
	},
	textarea: {
		name: "textarea",
		title: "Textarea",
		icon: LucideLetterText,
		blockTemplate: "textarea",
		initialState: { placeholder: "Textarea" },
	},
	select: {
		name: "select",
		title: "Select",
		icon: LucideChevronsUpDown,
		blockTemplate: "select",
	},
	img: {
		name: "img",
		title: "Image",
		icon: LucideImage,
		blockTemplate: "img",
	},
	form: {
		name: "form",
		title: "Form",
		icon: LucideClipboardList,
		blockTemplate: "form",
	},
}

export const NATIVE_ELEMENT_NAMES = Object.keys(NATIVE_ELEMENTS)

// Props panel schemas for native elements. These write to componentProps,
// which land on the element as plain HTML attributes.
const textContentProp: ComponentProps = {
	textContent: { type: "string", inputType: "text", default: "" },
}

const checkboxProp = { type: "boolean", inputType: "checkbox", default: false }
const textProp = { type: "string", inputType: "text" }

const NATIVE_ELEMENT_PROPS: Record<string, ComponentProps> = {
	button: {
		...textContentProp,
		type: { type: "string", inputType: "select", options: ["button", "submit", "reset"], default: "button" },
		disabled: checkboxProp,
	},
	a: {
		...textContentProp,
		href: { ...textProp, default: "#" },
		target: {
			type: "string",
			inputType: "select",
			options: ["_self", "_blank", "_parent", "_top"],
			default: "_self",
		},
	},
	label: {
		...textContentProp,
		for: textProp,
	},
	input: {
		type: {
			type: "string",
			inputType: "select",
			options: [
				"text", "number", "email", "password", "date", "time", "datetime-local",
				"search", "tel", "url", "color", "checkbox", "radio", "range", "file",
			],
			default: "text",
		},
		placeholder: textProp,
		name: textProp,
		value: textProp,
		required: checkboxProp,
		disabled: checkboxProp,
	},
	textarea: {
		placeholder: textProp,
		name: textProp,
		rows: { type: "number", inputType: "number" },
		required: checkboxProp,
		disabled: checkboxProp,
	},
	select: {
		name: textProp,
		multiple: checkboxProp,
		disabled: checkboxProp,
	},
	option: {
		...textContentProp,
		value: textProp,
		disabled: checkboxProp,
	},
	img: {
		src: textProp,
		alt: textProp,
		loading: { type: "string", inputType: "select", options: ["eager", "lazy"], default: "eager" },
	},
	form: {
		name: textProp,
	},
	iframe: {
		src: textProp,
		allow: textProp,
	},
	video: {
		src: textProp,
		controls: checkboxProp,
		autoplay: checkboxProp,
		loop: checkboxProp,
		muted: checkboxProp,
	},
	audio: {
		src: textProp,
		controls: checkboxProp,
	},
}

export function getNativeElementProps(tag: string): ComponentProps {
	const schema = NATIVE_ELEMENT_PROPS[tag]
	if (schema) return schema
	return isNativeTextTag(tag) ? { ...textContentProp } : {}
}
