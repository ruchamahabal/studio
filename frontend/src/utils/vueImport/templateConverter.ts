import type { BlockOptions } from "@/types"
import {
	FRAPPE_UI_COMPONENTS,
	FRAMEWORK_UI_COMPONENTS,
	STUDIO_COMPONENTS,
} from "../constants"
import { ExpressionRewriter } from "./expressions"
import type { ScriptScope } from "./scriptAnalyzer"

/**
 * Walks a parsed Vue template AST (vue/compiler-sfc parse output, pre-transform)
 * and emits Studio BlockOptions trees: elements → container/TextBlock, known
 * components → component blocks, v-if → visibilityCondition, v-for → Repeater,
 * v-model → { $type: "variable" } props, @event → "Run Script" events.
 */

// @vue/compiler-core enums, inlined to keep this module runnable outside Vite
const NodeType = { ELEMENT: 1, TEXT: 2, COMMENT: 3, INTERPOLATION: 5, ATTRIBUTE: 6, DIRECTIVE: 7 }
const TagType = { ELEMENT: 0, COMPONENT: 1, SLOT: 2, TEMPLATE: 3 }

// Registered in globals.ts but absent from the constants lists
const EXTRA_REGISTERED = [
	"Input", "ListItem", "LoadingIndicator", "LoadingText", "Popover", "Toast",
	"CommandPalette", "CommandPaletteItem", "RouterLink",
]
const KNOWN_COMPONENTS = new Set([
	...FRAPPE_UI_COMPONENTS,
	...FRAMEWORK_UI_COMPONENTS,
	...STUDIO_COMPONENTS,
	...EXTRA_REGISTERED,
])
const SKIPPED_BUILTINS = new Set(["Teleport", "Transition", "TransitionGroup", "KeepAlive", "Suspense"])
const CONTAINER_TAGS = new Set([
	"div", "section", "main", "article", "aside", "header", "footer", "nav", "form",
	"fieldset", "figure", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th",
])

interface Ctx {
	renames: Map<string, string>
}

interface ChildrenResult {
	children: BlockOptions[]
	slots: Record<string, BlockOptions[]>
	soleText: string | null
}

type IfEntry = { kind: "static"; truthy: boolean } | { kind: "dynamic"; expr: string }

export class TemplateConverter {
	rewriter: ExpressionRewriter
	private repeaterWarned = false

	constructor(private scope: ScriptScope, private warnings: string[]) {
		this.rewriter = new ExpressionRewriter(scope, warnings)
	}

	convertRoot(children: any[]): BlockOptions[] {
		const result = this.convertChildren(children, { renames: new Map() })
		const blocks = [...result.children]
		if (result.soleText) blocks.push(this.textBlock(result.soleText, "p"))
		if (Object.keys(result.slots).length) {
			this.warnings.push("Top-level <template #...> slots were ignored.")
		}
		return blocks
	}

	private convertChildren(nodes: any[], ctx: Ctx): ChildrenResult {
		const children: BlockOptions[] = []
		const slots: Record<string, BlockOptions[]> = {}
		const textParts: string[] = []
		let sawElement = false
		let ifChain: IfEntry[] = []

		const flushText = () => {
			const text = joinText(textParts)
			textParts.length = 0
			if (text) children.push(this.textBlock(text, "span"))
		}

		for (const node of nodes) {
			if (node.type === NodeType.COMMENT) continue
			if (node.type === NodeType.TEXT) {
				if (node.content.trim()) textParts.push(condenseWhitespace(node.content))
				else if (textParts.length) textParts.push(" ")
				continue
			}
			if (node.type === NodeType.INTERPOLATION) {
				const res = this.rewriter.resolve(node.content?.content ?? "", ctx.renames)
				textParts.push(res.kind === "static" ? String(res.value ?? "") : `{{ ${res.expr} }}`)
				ifChain = []
				continue
			}
			if (node.type !== NodeType.ELEMENT) continue

			const slotDir = findDirective(node, "slot")
			if (node.tag === "template" && slotDir) {
				const slotName = slotDir.arg?.content || "default"
				slots[slotName] = this.convertSlotContent(node, slotDir, ctx)
				continue
			}

			sawElement = true
			flushText()
			const { skip, condition, chain } = this.resolveVisibility(node, ifChain, ctx)
			ifChain = chain
			if (skip) continue
			const block = this.convertNode(node, ctx)
			if (!block) continue
			if (condition) block.visibilityCondition = `{{ ${condition} }}`
			children.push(block)
		}

		if (!sawElement && !children.length) {
			return { children, slots, soleText: joinText(textParts) || null }
		}
		flushText()
		return { children, slots, soleText: null }
	}

	convertNode(el: any, ctx: Ctx, skipFor = false): BlockOptions | null {
		const forDir = findDirective(el, "for")
		if (forDir && !skipFor) return this.convertFor(el, forDir, ctx)

		if (el.tagType === TagType.SLOT) {
			this.warnings.push("<slot> outlets can't be converted; skipped.")
			return null
		}
		if (el.tag === "component") {
			this.warnings.push("<component :is> can't be converted; skipped.")
			return null
		}
		if (SKIPPED_BUILTINS.has(el.tag)) {
			this.warnings.push(`<${el.tag}> isn't supported; skipped.`)
			return null
		}
		if (el.tag === "svg" || el.tag === "img" || findDirective(el, "html")) return this.htmlBlock(el, ctx)
		if (el.tag === "template") return this.wrapTemplate(el, ctx)
		if (el.tagType === TagType.COMPONENT || /^[A-Z]/.test(el.tag) || el.tag === "router-link") {
			return this.convertComponent(el, ctx)
		}
		return this.convertPlainElement(el, ctx)
	}

	private convertComponent(el: any, ctx: Ctx): BlockOptions | null {
		const componentName = el.tag === "router-link" ? "RouterLink" : el.tag
		if (!KNOWN_COMPONENTS.has(componentName)) {
			this.warnings.push(`Component "${componentName}" isn't available in Studio; skipped.`)
			return null
		}

		const block = emptyBlock(componentName)
		this.applyProps(el, block, ctx, true)

		let childCtx = ctx
		const slotDir = findDirective(el, "slot")
		if (slotDir) childCtx = this.slotScopeCtx(slotDir, ctx)

		const inner = this.convertChildren(el.children, childCtx)
		for (const [name, slotBlocks] of Object.entries(inner.slots)) {
			slotBlocks.forEach((slotBlock) => (slotBlock.parentSlotName = name))
			block.componentSlots![name] = { slotName: name, slotContent: slotBlocks }
		}
		if (inner.soleText) {
			if (inner.soleText.includes("{{")) block.children = [this.textBlock(inner.soleText, "span")]
			else block.componentSlots!.default = { slotName: "default", slotContent: inner.soleText }
		} else {
			block.children = inner.children
		}
		return block
	}

	private convertPlainElement(el: any, ctx: Ctx): BlockOptions {
		const inner = this.convertChildren(el.children, ctx)
		if (Object.keys(inner.slots).length) {
			this.warnings.push(`<template #...> inside <${el.tag}> was ignored.`)
		}

		const isEmpty = !inner.children.length
		if (isEmpty && (inner.soleText || !CONTAINER_TAGS.has(el.tag))) {
			const block = this.textBlock(inner.soleText ?? "", el.tag)
			this.applyProps(el, block, ctx, true)
			return block
		}

		const block = emptyBlock("container")
		block.originalElement = "div"
		if (el.tag !== "div" && !CONTAINER_TAGS.has(el.tag)) {
			this.warnings.push(`<${el.tag}> was converted to a div container.`)
		}
		this.applyProps(el, block, ctx, false)
		block.children = inner.children
		return block
	}

	private convertFor(el: any, dir: any, ctx: Ctx): BlockOptions | null {
		const parsed = parseForExpression(dir)
		if (!parsed) {
			this.warnings.push(`Could not parse v-for "${dir.exp?.content}"; rendered a single item.`)
			return this.convertNode(el, ctx, true)
		}
		if (!/^[A-Za-z_$][\w$]*$/.test(parsed.item)) {
			this.warnings.push(`Destructured v-for items ("${parsed.item}") aren't supported; bindings inside may not resolve.`)
		}

		const res = this.rewriter.resolve(parsed.source, ctx.renames)
		const data = res.kind === "static" ? toStorable(res.value) : `{{ ${res.expr} }}`

		const childRenames = new Map(ctx.renames)
		childRenames.set(parsed.item, "dataItem")
		if (parsed.index) childRenames.set(parsed.index, "dataIndex")
		const childCtx = { renames: childRenames }

		const child = this.convertNode(el, childCtx, true)
		if (!child) return null
		if (!this.repeaterWarned) {
			this.repeaterWarned = true
			this.warnings.push(
				"v-for became a Repeater, which wraps rows in its own flex container — check layout inside components like List.",
			)
		}

		const block = emptyBlock("Repeater")
		block.componentProps = { data }
		const dataKey = this.dataKeyFrom(el, parsed.item)
		if (dataKey) block.componentProps.dataKey = dataKey
		block.children = [child]
		return block
	}

	// ---- props, events, directives ----

	private applyProps(el: any, block: BlockOptions, ctx: Ctx, isComponent: boolean) {
		for (const prop of el.props ?? []) {
			if (prop.type === NodeType.ATTRIBUTE) this.applyStaticAttr(prop, block, isComponent)
			else if (prop.type === NodeType.DIRECTIVE) this.applyDirective(prop, block, ctx, isComponent)
		}
	}

	private applyStaticAttr(attr: any, block: BlockOptions, isComponent: boolean) {
		if (attr.name === "key" || attr.name === "ref") return
		const value = attr.value?.content ?? true
		if (attr.name === "class" && typeof value === "string") {
			block.classes = [...(block.classes || []), ...value.split(/\s+/).filter(Boolean)]
		} else if (attr.name === "style" && typeof value === "string") {
			Object.assign(block.baseStyles!, parseInlineStyle(value))
		} else if (isComponent) {
			block.componentProps![camelCase(attr.name)] = value
		} else {
			block.attributes![attr.name] = value
		}
	}

	private applyDirective(dir: any, block: BlockOptions, ctx: Ctx, isComponent: boolean) {
		switch (dir.name) {
			case "bind":
				return this.applyBind(dir, block, ctx, isComponent)
			case "on":
				return this.applyEvent(dir, block, ctx)
			case "model":
				return this.applyModel(dir, block)
			case "show": {
				const res = this.rewriter.resolve(dir.exp?.content ?? "", ctx.renames)
				if (res.kind === "dynamic") block.visibilityCondition = `{{ ${res.expr} }}`
				else if (!res.value) block.baseStyles!.display = "none"
				return
			}
			// handled by the tree walk / htmlBlock
			case "if": case "else-if": case "else": case "for": case "slot": case "html":
			case "cloak": case "once": case "memo": case "pre":
				return
			default:
				this.warnings.push(`Directive "v-${dir.name}" isn't supported; skipped.`)
		}
	}

	private applyBind(dir: any, block: BlockOptions, ctx: Ctx, isComponent: boolean) {
		const argName = dir.arg?.content
		if (!argName) {
			const res = this.rewriter.resolve(dir.exp?.content ?? "", ctx.renames)
			if (res.kind === "static" && res.value && typeof res.value === "object") {
				Object.assign(block.componentProps!, toStorable(res.value))
			} else {
				this.warnings.push("A v-bind object spread couldn't be converted; skipped.")
			}
			return
		}
		if (["key", "ref", "is"].includes(argName)) return

		const res = this.rewriter.resolve(dir.exp?.content ?? camelCase(argName), ctx.renames)
		if (argName === "class") return this.applyBoundClass(res, block)
		if (argName === "style") return this.applyBoundStyle(res, block)

		const propName = isComponent ? camelCase(argName) : argName
		if (res.kind === "static") {
			const value = toStorable(res.value)
			if (value !== undefined) block.componentProps![propName] = value
		} else {
			block.componentProps![propName] = `{{ ${res.expr} }}`
		}
	}

	private applyBoundClass(res: { kind: string; value?: any; expr?: string }, block: BlockOptions) {
		if (res.kind === "dynamic") {
			block.componentProps!.class = `{{ ${res.expr} }}`
			return
		}
		block.classes = [...(block.classes || []), ...normalizeClassValue(res.value)]
	}

	private applyBoundStyle(res: { kind: string; value?: any; expr?: string }, block: BlockOptions) {
		if (res.kind === "dynamic") {
			block.componentProps!.style = `{{ ${res.expr} }}`
		} else if (res.value && typeof res.value === "object") {
			for (const [key, value] of Object.entries(res.value)) {
				block.baseStyles![camelCase(key)] = value as string
			}
		}
	}

	private applyEvent(dir: any, block: BlockOptions, ctx: Ctx) {
		const eventName = dir.arg?.content
		if (!eventName) return
		const modifiers = (dir.modifiers || []).map((m: any) => m.content ?? m)
		if (modifiers.length) {
			this.warnings.push(`Event modifiers ("${eventName}.${modifiers.join(".")}") aren't supported; using plain "${eventName}".`)
		}
		const script = this.rewriter.buildEventScript(dir.exp?.content ?? "", ctx.renames)
		block.componentEvents![eventName] = { event: eventName, action: "Run Script", script }
	}

	private applyModel(dir: any, block: BlockOptions) {
		const propName = dir.arg?.content || "modelValue"
		const target = dir.exp?.content?.trim()
		if (target && this.scope.refNames.has(target)) {
			this.rewriter.usedRefs.add(target)
			block.componentProps![propName] = { $type: "variable", name: target }
		} else {
			this.warnings.push(`v-model target "${target}" isn't a script ref; the binding was skipped.`)
		}
	}

	// ---- helpers ----

	private convertSlotContent(node: any, slotDir: any, ctx: Ctx): BlockOptions[] {
		const childCtx = this.slotScopeCtx(slotDir, ctx)
		const inner = this.convertChildren(node.children, childCtx)
		const blocks = [...inner.children]
		if (inner.soleText) blocks.push(this.textBlock(inner.soleText, "span"))
		return blocks
	}

	/** Scoped slot values are forwarded as attrs by Studio, not into {{ }} scope —
	 * keep the names as-is (no rename/inline) and surface one warning. */
	private slotScopeCtx(slotDir: any, ctx: Ctx): Ctx {
		const exp = slotDir.exp?.content
		if (!exp) return ctx
		const names = exp.match(/[A-Za-z_$][\w$]*/g) || []
		if (!names.length) return ctx
		this.warnings.push(`Scoped slot values (${names.join(", ")}) aren't available in Studio; bindings using them may not resolve.`)
		const renames = new Map(ctx.renames)
		names.forEach((name: string) => renames.set(name, name))
		return { renames }
	}

	private resolveVisibility(el: any, chain: IfEntry[], ctx: Ctx) {
		const ifDir = findDirective(el, "if")
		const elseIfDir = findDirective(el, "else-if")
		const elseDir = findDirective(el, "else")
		if (!ifDir && !elseIfDir && !elseDir) return { skip: false, condition: null, chain: [] as IfEntry[] }

		const prior = ifDir ? [] : chain
		if (prior.some((entry) => entry.kind === "static" && entry.truthy)) {
			return { skip: true, condition: null, chain: prior }
		}
		const negations = prior
			.filter((entry): entry is Extract<IfEntry, { kind: "dynamic" }> => entry.kind === "dynamic")
			.map((entry) => `!(${entry.expr})`)

		let own: IfEntry | null = null
		if (ifDir || elseIfDir) {
			const res = this.rewriter.resolve((ifDir || elseIfDir).exp?.content ?? "", ctx.renames)
			own = res.kind === "static" ? { kind: "static", truthy: Boolean(res.value) } : { kind: "dynamic", expr: res.expr }
			if (own.kind === "static" && !own.truthy) {
				return { skip: true, condition: null, chain: [...prior, own] }
			}
		}

		const parts = [...negations]
		if (own?.kind === "dynamic") parts.push(`(${own.expr})`)
		return {
			skip: false,
			condition: parts.length ? parts.join(" && ") : null,
			chain: own ? [...prior, own] : prior,
		}
	}

	private dataKeyFrom(el: any, itemName: string): string | undefined {
		const keyDir = (el.props || []).find(
			(prop: any) => prop.type === NodeType.DIRECTIVE && prop.name === "bind" && prop.arg?.content === "key",
		)
		const match = keyDir?.exp?.content?.trim().match(new RegExp(`^${escapeRegExp(itemName)}\\??\\.(\\w+)$`))
		return match?.[1]
	}

	private textBlock(text: string, tag: string): BlockOptions {
		const block = emptyBlock("TextBlock")
		block.componentProps = { text, tag }
		return block
	}

	private htmlBlock(el: any, ctx: Ctx): BlockOptions {
		const block = emptyBlock("HTML")
		const htmlDir = findDirective(el, "html")
		if (htmlDir) {
			const res = this.rewriter.resolve(htmlDir.exp?.content ?? "", ctx.renames)
			block.componentProps = { html: res.kind === "static" ? String(res.value ?? "") : `{{ ${res.expr} }}` }
		} else {
			const source = el.loc?.source ?? ""
			if (/[:@]\w|\{\{/.test(source)) {
				this.warnings.push(`<${el.tag}> was copied verbatim into an HTML block; dynamic bindings inside it won't work.`)
			}
			block.componentProps = { html: source }
		}
		return block
	}

	private wrapTemplate(el: any, ctx: Ctx): BlockOptions | null {
		const inner = this.convertChildren(el.children, ctx)
		const children = [...inner.children]
		if (inner.soleText) children.push(this.textBlock(inner.soleText, "span"))
		if (!children.length) return null
		if (children.length === 1) return children[0]
		const block = emptyBlock("container")
		block.originalElement = "div"
		block.children = children
		return block
	}
}

function emptyBlock(componentName: string): BlockOptions {
	return {
		componentName,
		componentProps: {},
		componentSlots: {},
		componentEvents: {},
		attributes: {},
		baseStyles: {},
		children: [],
	}
}

function findDirective(el: any, name: string) {
	return (el.props || []).find((prop: any) => prop.type === NodeType.DIRECTIVE && prop.name === name)
}

function parseForExpression(dir: any): { item: string; index?: string; source: string } | null {
	const result = dir.forParseResult
	if (result?.source?.content && result?.value?.content) {
		return {
			item: result.value.content.trim(),
			index: (result.key?.content || result.index?.content)?.trim(),
			source: result.source.content.trim(),
		}
	}
	const match = dir.exp?.content?.match(/^\s*\(?\s*([^,()]+?)\s*(?:,\s*([\w$]+))?\s*\)?\s+(?:in|of)\s+(.+)$/s)
	if (!match) return null
	return { item: match[1].trim(), index: match[2]?.trim(), source: match[3].trim() }
}

/** Functions survive as their source strings — Studio revives function-shaped
 * strings at render (evaluateDynamicValues), matching how handler props are stored. */
function toStorable(value: any): any {
	if (value === undefined) return undefined
	try {
		return JSON.parse(JSON.stringify(value, (_key, val) => (typeof val === "function" ? val.toString() : val)))
	} catch {
		return undefined
	}
}

function normalizeClassValue(value: any): string[] {
	if (!value) return []
	if (typeof value === "string") return value.split(/\s+/).filter(Boolean)
	if (Array.isArray(value)) return value.flatMap(normalizeClassValue)
	if (typeof value === "object") {
		return Object.entries(value)
			.filter(([, condition]) => condition)
			.map(([name]) => name)
	}
	return []
}

function parseInlineStyle(style: string): Record<string, string> {
	const styles: Record<string, string> = {}
	for (const declaration of style.split(";")) {
		const [property, ...rest] = declaration.split(":")
		if (property?.trim() && rest.length) styles[camelCase(property.trim())] = rest.join(":").trim()
	}
	return styles
}

function camelCase(name: string): string {
	return name.replace(/-(\w)/g, (_match, char) => char.toUpperCase())
}

function condenseWhitespace(text: string): string {
	return text.replace(/\s+/g, " ")
}

function joinText(parts: string[]): string {
	return parts.join("").trim()
}

function escapeRegExp(text: string): string {
	return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}
