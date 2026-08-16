import type { BlockOptions, BlockStyleMap } from "@/types"

// seed styles so a freshly dropped element is visible and usable, never a zero-size tag
const fieldStyles: BlockStyleMap = {
	width: "100%",
	borderWidth: "1px",
	borderStyle: "solid",
	borderColor: "var(--outline-gray-2)",
	borderRadius: "6px",
	padding: "5px 8px",
	fontSize: "13px",
	backgroundColor: "var(--surface-white)",
	color: "var(--text-ink-gray-8)",
}

export const nativeTemplates = {
	section: (): BlockOptions => ({
		componentName: "section",
		baseStyles: {
			display: "flex",
			flexDirection: "column",
			gap: "8px",
			width: "100%",
			padding: "16px",
		},
	}),
	p: (): BlockOptions => ({
		componentName: "p",
		componentProps: { textContent: "Paragraph text" },
		baseStyles: {
			fontSize: "14px",
			lineHeight: "1.5",
			width: "fit-content",
			height: "fit-content",
			color: "var(--text-ink-gray-7)",
		},
	}),
	span: (): BlockOptions => ({
		componentName: "span",
		componentProps: { textContent: "Span" },
		baseStyles: {
			fontSize: "14px",
			width: "fit-content",
			height: "fit-content",
			color: "var(--text-ink-gray-7)",
		},
	}),
	pre: (): BlockOptions => ({
		componentName: "pre",
		componentProps: { textContent: "Preformatted text" },
		baseStyles: {
			fontFamily: "monospace",
			fontSize: "12px",
			padding: "12px",
			borderRadius: "6px",
			backgroundColor: "var(--surface-gray-1)",
			color: "var(--text-ink-gray-8)",
			overflow: "auto",
			width: "100%",
		},
	}),
	button: (): BlockOptions => ({
		componentName: "button",
		componentProps: { type: "button", textContent: "Button" },
		baseStyles: {
			display: "flex",
			alignItems: "center",
			justifyContent: "center",
			width: "fit-content",
			height: "fit-content",
			padding: "5px 12px",
			borderRadius: "6px",
			backgroundColor: "var(--surface-gray-7)",
			color: "var(--text-ink-white)",
			fontSize: "13px",
			fontWeight: "500",
			cursor: "pointer",
		},
	}),
	a: (): BlockOptions => ({
		componentName: "a",
		componentProps: { href: "#", textContent: "Link" },
		baseStyles: {
			width: "fit-content",
			height: "fit-content",
			fontSize: "14px",
			color: "var(--text-ink-blue-3)",
			textDecoration: "underline",
			cursor: "pointer",
		},
	}),
	input: (): BlockOptions => ({
		componentName: "input",
		componentProps: { type: "text", placeholder: "Input" },
		baseStyles: { ...fieldStyles },
	}),
	textarea: (): BlockOptions => ({
		componentName: "textarea",
		componentProps: { placeholder: "Textarea" },
		baseStyles: { ...fieldStyles, minHeight: "80px" },
	}),
	select: (): BlockOptions => ({
		componentName: "select",
		baseStyles: { ...fieldStyles },
		children: [
			{ componentName: "option", componentProps: { value: "option-1", textContent: "Option 1" } },
			{ componentName: "option", componentProps: { value: "option-2", textContent: "Option 2" } },
		],
	}),
	img: (): BlockOptions => ({
		componentName: "img",
		componentProps: { src: "https://blocks.astratic.com/img/general-img-square.png", alt: "" },
		baseStyles: {
			width: "200px",
			height: "200px",
			objectFit: "cover",
		},
	}),
	form: (): BlockOptions => ({
		componentName: "form",
		baseStyles: {
			display: "flex",
			flexDirection: "column",
			gap: "12px",
			width: "100%",
			maxWidth: "400px",
		},
	}),
} satisfies Record<string, () => BlockOptions>

export type NativeTemplate = keyof typeof nativeTemplates
