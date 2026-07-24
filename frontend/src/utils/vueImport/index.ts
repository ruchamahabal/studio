import { parse } from "vue/compiler-sfc"
import type { BlockOptions } from "@/types"
import { analyzeScript } from "./scriptAnalyzer"
import { TemplateConverter } from "./templateConverter"

export { isVueCode } from "./detect"

/**
 * Converts pasted Vue code (a full SFC or a bare template snippet — e.g. a
 * frappe-ui docs story/recipe) into Studio blocks plus the page variables its
 * dynamic bindings need. Deterministic: no AI involved.
 */

export interface NewPageVariable {
	variable_name: string
	variable_type: "String" | "Number" | "Boolean" | "Object"
	initial_value: string
}

export interface VueConversion {
	blocks: BlockOptions[]
	variables: NewPageVariable[]
	warnings: string[]
}

export function convertVueToBlocks(source: string): VueConversion {
	const sfcSource = /<template[\s>]/.test(source) ? source : `<template>\n${source}\n</template>`
	const { descriptor, errors } = parse(sfcSource, { filename: "Pasted.vue" })
	if (!descriptor.template?.ast) {
		throw new Error(errors[0]?.message || "No <template> content found in the pasted code")
	}

	const scope = analyzeScript(descriptor.scriptSetup?.content ?? descriptor.script?.content)
	const warnings = [...scope.warnings]
	errors.forEach((error: any) => warnings.push(`Parse error: ${error.message}`))

	const converter = new TemplateConverter(scope, warnings)
	const blocks = converter.convertRoot(descriptor.template.ast.children)
	const variables = buildVariables(scope, converter.rewriter.usedRefs)
	return { blocks, variables, warnings: [...new Set(warnings)] }
}

/** Only refs the converted template/events actually reference become page variables. */
function buildVariables(
	scope: ReturnType<typeof analyzeScript>,
	usedRefs: Set<string>,
): NewPageVariable[] {
	const variables: NewPageVariable[] = []
	for (const name of usedRefs) {
		const value = scope.refs[name]
		if (typeof value === "boolean") {
			variables.push({ variable_name: name, variable_type: "Boolean", initial_value: String(value) })
		} else if (typeof value === "number") {
			variables.push({ variable_name: name, variable_type: "Number", initial_value: String(value) })
		} else if (typeof value === "string") {
			// String initial values are stored JSON-quoted (see getInitialVariableValue)
			variables.push({ variable_name: name, variable_type: "String", initial_value: JSON.stringify(value) })
		} else {
			variables.push({
				variable_name: name,
				variable_type: "Object",
				initial_value: JSON.stringify(value ?? null),
			})
		}
	}
	return variables
}
