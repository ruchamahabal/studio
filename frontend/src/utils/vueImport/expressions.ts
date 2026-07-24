import { babelParse } from "vue/compiler-sfc"
import type { ScriptScope } from "./scriptAnalyzer"

/**
 * Rewrites template expressions into Studio's two binding forms:
 * - "static": every referenced name is a script constant, so the expression is
 *   evaluated once and its value baked into the block (Studio's AI does the same).
 * - "dynamic": the expression references page variables (refs) or repeater scope,
 *   so it stays a "{{ }}" string; v-for locals are renamed to dataItem/dataIndex
 *   and leftover constants are inlined as literals (they don't exist at runtime).
 * Event scripts additionally get refs rewritten to `name.value` — Studio scripts
 * see variables as refs, unlike templates which auto-unwrap.
 */

export type Resolution = { kind: "static"; value: any } | { kind: "dynamic"; expr: string }

const JS_GLOBALS = new Set([
	"undefined", "NaN", "Infinity", "Math", "JSON", "Date", "String", "Number", "Boolean",
	"Array", "Object", "RegExp", "Promise", "Set", "Map", "console", "window", "document",
	"location", "navigator", "parseInt", "parseFloat", "isNaN", "isFinite",
	"encodeURIComponent", "decodeURIComponent", "setTimeout", "clearTimeout",
])

interface FreeId {
	name: string
	start: number
	end: number
}

export class ExpressionRewriter {
	usedRefs = new Set<string>()
	private warnedNames = new Set<string>()

	constructor(private scope: ScriptScope, private warnings: string[]) {}

	resolve(rawExpr: string, renames: Map<string, string>): Resolution {
		const expr = rawExpr.trim()
		if (!expr) return { kind: "static", value: undefined }

		let free: FreeId[]
		try {
			free = collectFreeIdentifiers(parseExpression(expr))
		} catch {
			this.warn(`Could not parse expression "${truncate(expr)}"; kept as a dynamic binding.`)
			return { kind: "dynamic", expr }
		}

		const names = uniqueNames(free).filter((name) => !JS_GLOBALS.has(name))
		const hasScopeLocals = names.some(
			(name) => renames.has(name) || this.scope.refNames.has(name) || name === "$event",
		)
		const bakeable =
			!hasScopeLocals &&
			names.every((name) => name in this.scope.constants || name in this.scope.functionValues)
		if (bakeable) {
			const baked = this.evaluate(expr, names)
			if (baked) return baked
		}
		return { kind: "dynamic", expr: this.rewrite(expr, free, renames, "template") }
	}

	/** Convert an @event expression (inline statements, an arrow fn, or a named
	 * script-setup function) into a Studio "Run Script" body. */
	buildEventScript(content: string, renames: Map<string, string>): string {
		const trimmed = content.trim()
		if (!trimmed) return ""

		const namedFunction = this.scope.functions[trimmed]
		if (namedFunction) {
			this.markRefsUsedIn(namedFunction.body)
			return functionToScript(namedFunction.params, namedFunction.body, namedFunction.isExpressionBody)
		}

		const arrow = tryParseFunctionExpression(trimmed)
		if (arrow) {
			const params = arrow.params.map((p: any) => trimmed.slice(p.start - 1, p.end - 1).trim()).join(", ")
			const isExpressionBody = arrow.body.type !== "BlockStatement"
			const bodySource = isExpressionBody
				? trimmed.slice(arrow.body.start - 1, arrow.body.end - 1)
				: trimmed.slice(arrow.body.start, arrow.body.end - 2)
			const rewritten = this.rewriteScriptSource(bodySource, renames, collectParamNames(arrow.params))
			return functionToScript(params, rewritten.trim(), isExpressionBody)
		}

		return this.rewriteScriptSource(trimmed, renames, new Set())
	}

	private rewriteScriptSource(source: string, renames: Map<string, string>, bound: Set<string>): string {
		if (!source.trim()) return ""
		let free: FreeId[]
		try {
			const ast = babelParse(source, { sourceType: "script", plugins: ["typescript"], errorRecovery: true })
			free = collectFreeIdentifiers({ node: ast.program, offset: 0 })
		} catch {
			this.warn(`Could not parse event handler "${truncate(source)}"; kept as-is.`)
			return source
		}
		return this.rewrite(source, free, renames, "script", bound)
	}

	private rewrite(
		source: string,
		free: FreeId[],
		renames: Map<string, string>,
		mode: "template" | "script",
		bound: Set<string> = new Set(),
	): string {
		const edits: { start: number; end: number; text: string }[] = []
		for (const id of free) {
			if (bound.has(id.name) || JS_GLOBALS.has(id.name)) continue
			const replacement = this.replacementFor(id.name, renames, mode)
			if (replacement !== null) edits.push({ start: id.start, end: id.end, text: replacement })
		}
		edits.sort((a, b) => b.start - a.start)
		let result = source
		for (const edit of edits) {
			result = result.slice(0, edit.start) + edit.text + result.slice(edit.end)
		}
		return result
	}

	private replacementFor(name: string, renames: Map<string, string>, mode: "template" | "script"): string | null {
		if (renames.has(name)) return renames.get(name)!
		if (this.scope.refNames.has(name)) {
			this.usedRefs.add(name)
			return mode === "script" ? `${name}.value` : null
		}
		if (name === "$event") return mode === "script" ? "(eventArgs[0])" : null
		if (name in this.scope.constants) return inlineLiteral(this.scope.constants[name])
		if (name in this.scope.functionValues) return `(${this.scope.functionValues[name].toString()})`
		if (this.scope.propNames.has(name)) {
			this.warn(`"${name}" is a prop of the pasted component and has no value in Studio.`)
		} else {
			this.warn(`"${name}" isn't available on the page; the binding may not resolve.`)
		}
		return null
	}

	private evaluate(expr: string, names: string[]): Resolution | null {
		try {
			const args = names.map((name) =>
				name in this.scope.constants ? this.scope.constants[name] : this.scope.functionValues[name],
			)
			const value = new Function(...names, `"use strict"; return (${expr});`)(...args)
			return { kind: "static", value }
		} catch (error: any) {
			this.warn(`Could not evaluate "${truncate(expr)}" (${error.message}); kept as a dynamic binding.`)
			return null
		}
	}

	markRefsUsedIn(source: string) {
		for (const name of this.scope.refNames) {
			if (new RegExp(`\\b${name}\\b`).test(source)) this.usedRefs.add(name)
		}
	}

	private warn(message: string) {
		if (this.warnedNames.has(message)) return
		this.warnedNames.add(message)
		this.warnings.push(message)
	}
}

function functionToScript(params: string, body: string, isExpressionBody: boolean): string {
	const statements = isExpressionBody ? `return ${body}` : body
	if (!params) return statements
	// executeUserScript calls handleEvent(...eventArgs), passing the DOM/emit payload through
	return `function handleEvent(${params}) {\n${statements}\n}`
}

/** Parse an expression; returned node ranges are offset by the wrapping "(". */
function parseExpression(expr: string): { node: any; offset: number } {
	const ast = babelParse(`(${expr}\n)`, { sourceType: "script", plugins: ["typescript"] })
	return { node: ast.program.body[0].expression, offset: 1 }
}

function tryParseFunctionExpression(source: string): any | null {
	try {
		const node = parseExpression(source).node
		return ["ArrowFunctionExpression", "FunctionExpression"].includes(node.type) ? node : null
	} catch {
		return null
	}
}

function collectParamNames(params: any[]): Set<string> {
	const names = new Set<string>()
	const visit = (pattern: any) => {
		if (!pattern || typeof pattern !== "object") return
		if (pattern.type === "Identifier") names.add(pattern.name)
		else if (pattern.type === "ObjectPattern") pattern.properties.forEach((p: any) => visit(p.value || p.argument))
		else if (pattern.type === "ArrayPattern") pattern.elements.forEach(visit)
		else if (pattern.type === "AssignmentPattern") visit(pattern.left)
		else if (pattern.type === "RestElement") visit(pattern.argument)
	}
	params.forEach(visit)
	return names
}

function collectFreeIdentifiers(parsed: { node: any; offset: number }): FreeId[] {
	const out: FreeId[] = []
	walk(parsed.node, null, "", [new Set()], out, parsed.offset)
	return out
}

function walk(
	node: any,
	parent: any,
	keyInParent: string,
	scopes: Set<string>[],
	out: FreeId[],
	offset: number,
) {
	if (!node || typeof node !== "object") return
	if (Array.isArray(node)) {
		node.forEach((child) => walk(child, parent, keyInParent, scopes, out, offset))
		return
	}
	if (typeof node.type !== "string") return

	if (node.type === "Identifier") {
		if (isNonValuePosition(parent, keyInParent, node)) return
		if (scopes.some((scope) => scope.has(node.name))) return
		out.push({ name: node.name, start: node.start - offset, end: node.end - offset })
		return
	}

	if (["ArrowFunctionExpression", "FunctionExpression", "FunctionDeclaration", "ObjectMethod"].includes(node.type)) {
		const localScope = collectParamNames(node.params || [])
		if (node.id?.name) localScope.add(node.id.name)
		scopes.push(localScope)
		walk(node.body, node, "body", scopes, out, offset)
		// default values in params can reference the outer scope
		;(node.params || []).forEach((param: any) => {
			if (param.type === "AssignmentPattern") walk(param.right, param, "right", scopes, out, offset)
		})
		scopes.pop()
		return
	}

	if (node.type === "VariableDeclarator") {
		collectParamNames([node.id]).forEach((name) => scopes[scopes.length - 1].add(name))
		walk(node.init, node, "init", scopes, out, offset)
		return
	}

	for (const key of Object.keys(node)) {
		if (key === "loc" || key === "leadingComments" || key === "trailingComments") continue
		walk(node[key], node, key, scopes, out, offset)
	}
}

function isNonValuePosition(parent: any, keyInParent: string, node: any): boolean {
	if (!parent) return false
	if (
		(parent.type === "MemberExpression" || parent.type === "OptionalMemberExpression") &&
		keyInParent === "property" &&
		!parent.computed
	) {
		return true
	}
	if ((parent.type === "ObjectProperty" || parent.type === "ObjectMethod") && keyInParent === "key" && !parent.computed) {
		return true
	}
	if (parent.type === "LabeledStatement" && keyInParent === "label") return true
	return false
}

function inlineLiteral(value: any): string {
	try {
		const json = JSON.stringify(value, (_key, val) => (typeof val === "function" ? val.toString() : val))
		return json === undefined ? "undefined" : `(${json})`
	} catch {
		return "undefined"
	}
}

function uniqueNames(free: FreeId[]): string[] {
	return [...new Set(free.map((id) => id.name))]
}

function truncate(text: string): string {
	return text.length > 60 ? `${text.slice(0, 60)}…` : text
}
