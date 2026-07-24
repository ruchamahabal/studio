import { babelParse } from "vue/compiler-sfc"

/**
 * Analyzes a pasted SFC's <script setup> so the template converter can decide,
 * per binding, between baking a literal value and leaving a dynamic {{ }} expression:
 * - ref()/computed() consts become Studio page variables (dynamic bindings)
 * - plain consts are evaluated to real values (baked into props)
 * - functions keep their source (inlined into event scripts, which see variables as refs)
 * Evaluation runs the script through new Function with Vue APIs stubbed out — the same
 * trust level as Studio page scripts, which already evaluate pasted strings.
 */

export interface FunctionInfo {
	params: string
	body: string
	isExpressionBody: boolean
}

export interface ScriptScope {
	constants: Record<string, any>
	refs: Record<string, any> // ref/computed name -> unwrapped initial value
	refNames: Set<string>
	functions: Record<string, FunctionInfo>
	functionValues: Record<string, any>
	propNames: Set<string>
	warnings: string[]
}

export function analyzeScript(script: string | null | undefined): ScriptScope {
	const scope = emptyScope()
	if (!script?.trim()) return scope

	let ast: any
	try {
		ast = babelParse(script, { sourceType: "module", plugins: ["typescript"] })
	} catch (error: any) {
		scope.warnings.push(`Could not parse the <script> block: ${error.message}`)
		return scope
	}

	const imports = collectImports(ast)
	const cleaned = blankRanges(script, collectStripRanges(ast, script))
	const declared = collectDeclarations(ast)
	const values = evaluateScript(cleaned, imports, declared.names, scope)
	classifyValues(values, declared, scope)
	extractFunctions(cleaned, declared.functionNodes, scope)
	return scope
}

function emptyScope(): ScriptScope {
	return {
		constants: {},
		refs: {},
		refNames: new Set(),
		functions: {},
		functionValues: {},
		propNames: new Set(),
		warnings: [],
	}
}

interface ImportedName {
	name: string
	source: string
}

function collectImports(ast: any): ImportedName[] {
	const imports: ImportedName[] = []
	const seen = new Set<string>()
	for (const stmt of ast.program.body) {
		if (stmt.type !== "ImportDeclaration") continue
		for (const spec of stmt.specifiers) {
			const name = spec.local?.name
			if (name && !seen.has(name)) {
				seen.add(name)
				imports.push({ name, source: stmt.source.value })
			}
		}
	}
	return imports
}

// Node types where TS wraps an expression (`x as T`, `x!`); only the suffix is stripped.
const TS_EXPRESSION_WRAPPERS = new Set([
	"TSAsExpression",
	"TSSatisfiesExpression",
	"TSNonNullExpression",
	"TSInstantiationExpression",
])

/** Ranges of imports + TypeScript-only syntax, blanked before evaluating as plain JS. */
function collectStripRanges(node: any, source: string, ranges: [number, number][] = []): [number, number][] {
	if (!node || typeof node !== "object") return ranges
	if (Array.isArray(node)) {
		node.forEach((child) => collectStripRanges(child, source, ranges))
		return ranges
	}
	if (typeof node.type !== "string") return ranges

	if (node.type === "ImportDeclaration") {
		ranges.push([node.start, node.end])
		return ranges
	}
	if (TS_EXPRESSION_WRAPPERS.has(node.type)) {
		ranges.push([node.expression.end, node.end])
		collectStripRanges(node.expression, source, ranges)
		return ranges
	}
	if (node.type.startsWith("TS")) {
		ranges.push([node.start, node.end])
		return ranges
	}
	// optional param marker: `a?: string` leaves a dangling `?` once the annotation is blanked
	if (node.optional && node.typeAnnotation && source[node.typeAnnotation.start - 1] === "?") {
		ranges.push([node.typeAnnotation.start - 1, node.typeAnnotation.start])
	}
	for (const key of Object.keys(node)) {
		if (key === "loc") continue
		collectStripRanges(node[key], source, ranges)
	}
	return ranges
}

function blankRanges(source: string, ranges: [number, number][]): string {
	const chars = source.split("")
	for (const [start, end] of ranges) {
		for (let i = start; i < end; i++) {
			if (chars[i] !== "\n") chars[i] = " "
		}
	}
	return chars.join("")
}

interface Declarations {
	names: string[]
	refNames: Set<string>
	functionNodes: { name: string; node: any }[]
}

function collectDeclarations(ast: any): Declarations {
	const declared: Declarations = { names: [], refNames: new Set(), functionNodes: [] }
	for (const stmt of ast.program.body) {
		if (stmt.type === "FunctionDeclaration" && stmt.id) {
			declared.names.push(stmt.id.name)
			declared.functionNodes.push({ name: stmt.id.name, node: stmt })
		}
		if (stmt.type !== "VariableDeclaration") continue
		for (const declarator of stmt.declarations) {
			if (declarator.id.type !== "Identifier") {
				collectPatternNames(declarator.id, declared.names)
				continue
			}
			const name = declarator.id.name
			declared.names.push(name)
			const init = unwrapTsExpression(declarator.init)
			if (!init) continue
			if (
				init.type === "CallExpression" &&
				init.callee.type === "Identifier" &&
				["ref", "shallowRef", "computed", "defineModel"].includes(init.callee.name)
			) {
				declared.refNames.add(name)
			}
			if (["ArrowFunctionExpression", "FunctionExpression"].includes(init.type)) {
				declared.functionNodes.push({ name, node: init })
			}
		}
	}
	return declared
}

function collectPatternNames(pattern: any, names: string[]) {
	if (!pattern || typeof pattern !== "object") return
	if (pattern.type === "Identifier") {
		names.push(pattern.name)
	} else if (pattern.type === "ObjectPattern") {
		pattern.properties.forEach((prop: any) => collectPatternNames(prop.value || prop.argument, names))
	} else if (pattern.type === "ArrayPattern") {
		pattern.elements.forEach((el: any) => collectPatternNames(el, names))
	} else if (pattern.type === "AssignmentPattern" || pattern.type === "RestElement") {
		collectPatternNames(pattern.left || pattern.argument, names)
	}
}

function unwrapTsExpression(node: any) {
	while (node && TS_EXPRESSION_WRAPPERS.has(node.type)) node = node.expression
	return node
}

function evaluateScript(
	cleaned: string,
	imports: ImportedName[],
	names: string[],
	scope: ScriptScope,
): Record<string, any> {
	const importPreamble = imports
		.map((imp) => `const ${imp.name} = __stubs.resolveImport(${JSON.stringify(imp.name)}, ${JSON.stringify(imp.source)});`)
		.join("\n")
	const macroPreamble =
		"const defineProps = __stubs.defineProps, withDefaults = __stubs.withDefaults," +
		" defineEmits = __stubs.defineEmits, defineModel = __stubs.defineModel," +
		" defineExpose = __stubs.noop, defineOptions = __stubs.noop, defineSlots = __stubs.defineSlots;"
	const source = `"use strict";\n${macroPreamble}\n${importPreamble}\n${cleaned}\n;return { ${names.join(", ")} };`
	try {
		return new Function("__stubs", source)(makeStubs(scope))
	} catch (error: any) {
		scope.warnings.push(`Could not evaluate script values (${error.message}); some bindings may stay dynamic.`)
		return {}
	}
}

function makeStubs(scope: ScriptScope) {
	const noop = () => {}
	const refLike = (value?: any) => ({ value })
	const safeCall = (fn: any) => {
		try {
			return typeof fn === "function" ? fn() : undefined
		} catch {
			return undefined
		}
	}
	const vueStubs: Record<string, any> = {
		ref: refLike,
		shallowRef: refLike,
		computed: (fn: any) => refLike(safeCall(fn?.get || fn)),
		reactive: (v: any) => v,
		readonly: (v: any) => v,
		markRaw: (v: any) => v,
		toRaw: (v: any) => v,
		unref: (v: any) => (v && typeof v === "object" && "value" in v ? v.value : v),
		toRefs: (v: any) => v,
		toRef: (v: any, key: any) => refLike(v?.[key]),
		nextTick: () => Promise.resolve(),
		h: () => null,
		defineAsyncComponent: (v: any) => v,
		useAttrs: () => ({}),
		useSlots: () => ({}),
		useTemplateRef: refLike,
		getCurrentInstance: () => null,
	}
	return {
		noop,
		defineProps: (definition: any) => {
			recordPropNames(definition, scope)
			return {}
		},
		withDefaults: (_props: any, defaults: any) => ({ ...defaults }),
		defineEmits: () => noop,
		defineModel: () => refLike(),
		defineSlots: () => ({}),
		resolveImport(name: string, source: string) {
			if (source === "vue") return vueStubs[name] ?? noop
			if (source.startsWith(".") || source.endsWith(".vue")) {
				scope.warnings.push(`External component "${name}" (from "${source}") isn't available in Studio; its usages were skipped.`)
				return { __vueImportComponent: name }
			}
			if (/^[A-Z]/.test(name)) return { __vueImportComponent: name }
			return noop
		},
	}
}

function recordPropNames(definition: any, scope: ScriptScope) {
	if (Array.isArray(definition)) {
		definition.forEach((name) => typeof name === "string" && scope.propNames.add(name))
	} else if (definition && typeof definition === "object") {
		Object.keys(definition).forEach((name) => scope.propNames.add(name))
	}
}

function classifyValues(values: Record<string, any>, declared: Declarations, scope: ScriptScope) {
	scope.refNames = declared.refNames
	const functionNames = new Set(declared.functionNodes.map((fn) => fn.name))
	for (const name of declared.names) {
		const value = values[name]
		if (typeof value === "function") scope.functionValues[name] = value
		if (functionNames.has(name)) continue
		if (declared.refNames.has(name)) {
			scope.refs[name] = value && typeof value === "object" && "value" in value ? value.value : value
			continue
		}
		if (value?.__vueImportComponent) continue
		if (typeof value === "function") continue
		scope.constants[name] = value
	}
}

function extractFunctions(cleaned: string, functionNodes: { name: string; node: any }[], scope: ScriptScope) {
	for (const { name, node } of functionNodes) {
		const params = (node.params || [])
			.map((param: any) => cleaned.slice(param.start, param.end).trim())
			.join(", ")
		const isExpressionBody = node.body.type !== "BlockStatement"
		const body = isExpressionBody
			? cleaned.slice(node.body.start, node.body.end).trim()
			: cleaned.slice(node.body.start + 1, node.body.end - 1).trim()
		scope.functions[name] = { params, body, isExpressionBody }
	}
}
