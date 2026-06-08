// Maps a Vue template AST into a Studio block tree. Native tags become native
// blocks, local composite components become custom-vue blocks, and plain HTML
// containers become container blocks. v-if -> visibilityCondition, @event ->
// Run Script events, :bind / {{ }} -> dynamic prop strings, v-model -> variable
// bindings, v-for -> Repeater wrapper.

import { NodeTypes, ElementTypes } from "@vue/compiler-core"

import { classifyTag, isContainerHtmlTag } from "./registry"
import type { ManifestBlock, ImportMap, ImportNote } from "./types"

export interface MapContext {
	pageName: string
	imports: ImportMap
	customComponents: Map<string, string> // name -> import source
	report: ImportNote[]
}

const CONTAINER_STYLES = {
	display: "flex",
	flexDirection: "column",
	flexShrink: 0,
	position: "static",
	width: "100%",
}

export function mapTemplateChildren(astNode: any, ctx: MapContext): ManifestBlock[] {
	return mapChildren(astNode?.children || [], ctx)
}

function mapChildren(children: any[], ctx: MapContext): ManifestBlock[] {
	const blocks: ManifestBlock[] = []
	for (const node of children) {
		if (node.type === NodeTypes.ELEMENT) {
			// a plain <template> wrapper (not a named slot) just contributes its children
			if (node.tagType === ElementTypes.TEMPLATE && !getSlotName(node)) {
				blocks.push(...mapChildren(node.children, ctx))
				continue
			}
			const block = mapElement(node, ctx)
			if (block) blocks.push(block)
		} else if (node.type === NodeTypes.TEXT) {
			const text = node.content.trim()
			if (text) blocks.push(textBlock(text, ctx))
		} else if (node.type === NodeTypes.INTERPOLATION) {
			blocks.push(textBlock(`{{ ${node.content.content} }}`, ctx))
		}
	}
	return blocks
}

function mapElement(node: any, ctx: MapContext): ManifestBlock | null {
	const tag = node.tag
	const kind = classifyTag(tag, node.tagType)
	const parsed = parseProps(node.props || [], ctx)

	const block: ManifestBlock = {
		componentId: genId(tag),
		componentName: tag,
		blockName: tag,
	}
	if (Object.keys(parsed.props).length) block.componentProps = parsed.props
	if (Object.keys(parsed.events).length) block.componentEvents = parsed.events
	if (parsed.visibility) block.visibilityCondition = parsed.visibility

	// split children into named slots vs normal children
	const { slots, normalChildren } = splitSlots(node.children || [])
	const childBlocks = mapChildren(normalChildren, ctx)
	if (childBlocks.length) block.children = childBlocks
	if (Object.keys(slots).length) {
		block.componentSlots = {}
		for (const [slotName, slotNodes] of Object.entries(slots)) {
			block.componentSlots[slotName] = {
				slotName,
				slotContent: mapChildren(slotNodes, ctx),
			}
		}
	}

	applyKind(block, tag, kind, ctx)

	return parsed.forExpr ? wrapInRepeater(block, parsed.forExpr, ctx) : block
}

function applyKind(block: ManifestBlock, tag: string, kind: string, ctx: MapContext) {
	if (kind === "custom") {
		block.isCustomVueComponent = true
		if (!ctx.customComponents.has(tag)) {
			ctx.customComponents.set(tag, ctx.imports[tag] || "")
			ctx.report.push({
				page: ctx.pageName,
				kind: "custom-wrapped",
				detail: `<${tag}> wrapped as custom Vue component (${ctx.imports[tag] || "unresolved import"})`,
			})
		}
	} else if (kind === "html") {
		block.originalElement = tag
		if (isContainerHtmlTag(tag)) {
			block.componentName = "container"
			block.baseStyles = { ...CONTAINER_STYLES }
		}
	}
	// "native": componentName stays as the tag
}

interface ParsedProps {
	props: Record<string, any>
	events: Record<string, any>
	visibility?: string
	forExpr?: string
}

function parseProps(propsArr: any[], ctx: MapContext): ParsedProps {
	const out: ParsedProps = { props: {}, events: {} }
	const vModels: { prop: string; expr: string }[] = []

	for (const p of propsArr) {
		if (p.type === NodeTypes.ATTRIBUTE) {
			if (p.name === "ref" || p.name === "key") continue // Vue template internals, not props
			out.props[p.name] = p.value ? p.value.content : true
		} else if (p.type === NodeTypes.DIRECTIVE) {
			handleDirective(p, out, vModels, ctx)
		}
	}

	for (const { prop, expr } of vModels) {
		out.props[prop] = isIdentifier(expr) ? { $type: "variable", name: expr } : dyn(expr)
	}
	return out
}

function handleDirective(p: any, out: ParsedProps, vModels: any[], ctx: MapContext) {
	const arg = p.arg?.content
	const expr = p.exp?.content
	switch (p.name) {
		case "bind":
			if (arg) out.props[arg] = dyn(expr)
			break
		case "on":
			if (arg) out.events[arg] = { event: arg, action: "Run Script", script: expr }
			break
		case "if":
		case "show":
			out.visibility = dyn(expr)
			break
		case "else-if":
			out.visibility = dyn(expr)
			ctx.report.push({ page: ctx.pageName, kind: "unsupported", detail: "v-else-if chaining flattened to a visibility condition" })
			break
		case "else":
			ctx.report.push({ page: ctx.pageName, kind: "unsupported", detail: "v-else has no Studio equivalent; block always rendered" })
			break
		case "model":
			vModels.push({ prop: arg || "modelValue", expr })
			break
		case "for":
			out.forExpr = expr
			break
		case "slot":
			break // handled by splitSlots on the parent
		default:
			ctx.report.push({ page: ctx.pageName, kind: "unsupported", detail: `directive v-${p.name} dropped` })
	}
}

function splitSlots(children: any[]): { slots: Record<string, any[]>; normalChildren: any[] } {
	const slots: Record<string, any[]> = {}
	const normalChildren: any[] = []
	for (const child of children) {
		const slotName = child.type === NodeTypes.ELEMENT ? getSlotName(child) : null
		if (slotName) {
			slots[slotName] = child.children || []
		} else {
			normalChildren.push(child)
		}
	}
	return { slots, normalChildren }
}

function getSlotName(node: any): string | null {
	if (node.tagType !== ElementTypes.TEMPLATE) return null
	const slotDir = (node.props || []).find((p: any) => p.type === NodeTypes.DIRECTIVE && p.name === "slot")
	if (!slotDir) return null
	return slotDir.arg?.content || "default"
}

function wrapInRepeater(block: ManifestBlock, forExpr: string, ctx: MapContext): ManifestBlock {
	ctx.report.push({ page: ctx.pageName, kind: "info", detail: `v-for "${forExpr}" wrapped in a Repeater` })
	return {
		componentId: genId("Repeater"),
		componentName: "Repeater",
		blockName: "Repeater",
		componentProps: { dataSource: dyn(forExpr.split(/\s+in\s+/).pop()?.trim() || forExpr) },
		children: [block],
	}
}

function textBlock(text: string, _ctx: MapContext): ManifestBlock {
	return {
		componentId: genId("TextBlock"),
		componentName: "TextBlock",
		blockName: "TextBlock",
		componentProps: { text, tag: "span" },
	}
}

function dyn(expr: string | undefined): string {
	return `{{ ${(expr || "").trim()} }}`
}

function isIdentifier(expr: string): boolean {
	return /^[a-zA-Z_$][\w$]*$/.test((expr || "").trim())
}

let idCounter = 0
function genId(name: string): string {
	idCounter += 1
	return `${name}-${idCounter.toString(36)}${Math.random().toString(36).slice(2, 7)}`
}
