// Parses a .vue SFC into a template AST + raw <script setup> content using the
// official Vue compiler, and extracts the import map via Babel.

import { readFileSync } from "node:fs"
import { parse as parseSfc } from "vue/compiler-sfc"
import babelParser from "@babel/parser"

import type { ImportMap } from "./types"

export interface ParsedSfc {
	templateAst: any | null // RootNode from @vue/compiler-core
	scriptContent: string
	imports: ImportMap
}

export function parseVueFile(filePath: string): ParsedSfc {
	const source = readFileSync(filePath, "utf-8")
	const { descriptor } = parseSfc(source, { filename: filePath })

	const scriptContent = descriptor.scriptSetup?.content || descriptor.script?.content || ""

	return {
		templateAst: descriptor.template?.ast || null,
		scriptContent,
		imports: extractImports(scriptContent),
	}
}

// Maps each locally imported identifier to its source string, e.g.
// "ViewControls" -> "@/components/ViewControls.vue"
function extractImports(scriptContent: string): ImportMap {
	const imports: ImportMap = {}
	if (!scriptContent) return imports

	const ast = babelParser.parse(scriptContent, {
		sourceType: "module",
		plugins: ["jsx", "topLevelAwait"],
	})

	for (const node of ast.program.body) {
		if (node.type !== "ImportDeclaration") continue
		const source = node.source.value
		for (const spec of node.specifiers) {
			imports[spec.local.name] = source
		}
	}
	return imports
}
