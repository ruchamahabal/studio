// Analyzes a <script setup> block: turns ref/reactive into Studio variables,
// computed into client scripts, watch into watchers, and create*Resource/call
// into Studio resources. Walks only top-level statements (no @babel/traverse).

import babelParser from "@babel/parser"

import type {
	ManifestVariable,
	ManifestWatcher,
	ManifestClientScript,
	ManifestResource,
} from "./types"

export interface ScriptAnalysis {
	variables: ManifestVariable[]
	watchers: ManifestWatcher[]
	clientScripts: ManifestClientScript[]
	resources: ManifestResource[]
	storeCalls: string[] // e.g. ["getMeta('Contact')", "organizationsStore()"] - unsupported
}

const RESOURCE_CALLEES: Record<string, ManifestResource["resource_type"]> = {
	createListResource: "Document List",
	createDocumentResource: "Document",
	createResource: "API Resource",
}

export function analyzeScript(content: string): ScriptAnalysis {
	const result: ScriptAnalysis = {
		variables: [],
		watchers: [],
		clientScripts: [],
		resources: [],
		storeCalls: [],
	}
	if (!content) return result

	const ast = babelParser.parse(content, {
		sourceType: "module",
		plugins: ["jsx", "topLevelAwait"],
	})
	const slice = (node: any) => content.slice(node.start, node.end)

	for (const node of ast.program.body) {
		// expression statements like `const { x } = store()` are declarations;
		// bare store calls are handled when they initialise a variable below
		if (node.type === "VariableDeclaration") {
			handleDeclaration(node, slice, result)
		} else if (node.type === "ExpressionStatement" && node.expression.type === "CallExpression") {
			const callee = calleeName(node.expression)
			if (callee === "watch") addWatcher(node.expression, slice, result)
		}
	}
	return result
}

function handleDeclaration(node: any, slice: (n: any) => string, result: ScriptAnalysis) {
	for (const decl of node.declarations) {
		const init = decl.init
		if (!init || init.type !== "CallExpression") continue
		const callee = calleeName(init)

		if (callee === "ref" || callee === "reactive") {
			result.variables.push(toVariable(decl, init, slice))
		} else if (callee === "computed") {
			const name = decl.id.name || "computed"
			result.clientScripts.push({ name_hint: name, script: slice(node) })
		} else if (callee === "watch") {
			addWatcher(init, slice, result)
		} else if (RESOURCE_CALLEES[callee]) {
			result.resources.push(toResource(decl, init, callee, slice))
		} else if (isStoreCall(callee)) {
			result.storeCalls.push(slice(init))
		}
	}
}

function toVariable(decl: any, init: any, slice: (n: any) => string): ManifestVariable {
	const arg = init.arguments[0]
	return {
		variable_name: decl.id.name,
		variable_type: inferType(arg),
		initial_value: arg ? slice(arg) : "",
	}
}

function inferType(arg: any): ManifestVariable["variable_type"] {
	if (!arg) return "Object"
	switch (arg.type) {
		case "BooleanLiteral":
			return "Boolean"
		case "NumericLiteral":
			return "Number"
		case "StringLiteral":
		case "TemplateLiteral":
			return "String"
		default:
			return "Object"
	}
}

function toResource(
	decl: any,
	init: any,
	callee: string,
	slice: (n: any) => string,
): ManifestResource {
	const config = init.arguments[0]
	const props = objectProps(config, slice)
	const resource: ManifestResource = {
		resource_name: decl.id.name,
		resource_type: RESOURCE_CALLEES[callee],
	}
	if (props.doctype) resource.document_type = unquote(props.doctype)
	if (props.url) resource.url = unquote(props.url)
	if (props.fields) resource.fields = props.fields
	if (props.filters) resource.filters = props.filters
	if (props.transform) resource.transform = props.transform
	if (props.onSuccess) resource.on_success = props.onSuccess
	if (props.onError) resource.on_error = props.onError
	return resource
}

function addWatcher(call: any, slice: (n: any) => string, result: ScriptAnalysis) {
	const [source, cb, opts] = call.arguments
	if (!source || !cb) return
	const options = opts ? objectProps(opts, slice) : {}
	result.watchers.push({
		source: slice(source),
		script: slice(cb),
		immediate: options.immediate === "true" ? 1 : 0,
		deep: options.deep === "true" ? 1 : 0,
	})
}

// Returns a map of object-expression property name -> raw source text of value.
function objectProps(node: any, slice: (n: any) => string): Record<string, string> {
	const out: Record<string, string> = {}
	if (!node || node.type !== "ObjectExpression") return out
	for (const prop of node.properties) {
		if (prop.type !== "ObjectProperty" && prop.type !== "ObjectMethod") continue
		const key = prop.key?.name || prop.key?.value
		if (!key) continue
		out[key] = prop.type === "ObjectMethod" ? slice(prop) : slice(prop.value)
	}
	return out
}

function calleeName(call: any): string {
	if (call.callee?.type === "Identifier") return call.callee.name
	if (call.callee?.type === "MemberExpression") return call.callee.property?.name || ""
	return ""
}

function isStoreCall(callee: string): boolean {
	return /store$/i.test(callee) || /^get[A-Z]/.test(callee)
}

function unquote(text: string): string {
	return text.replace(/^['"`]|['"`]$/g, "")
}
