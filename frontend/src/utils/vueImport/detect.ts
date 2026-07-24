// Lightweight Vue-code detection for the paste handler. Kept free of imports so the
// heavy converter (vue/compiler-sfc) stays in its own lazy chunk.
export function isVueCode(text: string): boolean {
	const trimmed = text.trim()
	if (!trimmed.startsWith("<")) return false
	if (/<template[\s>]/.test(trimmed) || /<script[\s>]/.test(trimmed)) return true
	// PascalCase component tag, e.g. <Button>, <ListRow ...>
	if (/<[A-Z][A-Za-z0-9]*[\s/>]/.test(trimmed)) return true
	// Vue directives / binding shorthands on plain markup
	if (/\sv-(if|else|else-if|for|model|bind|on|show|html|slot)\b/.test(trimmed)) return true
	return /\s[:@][a-zA-Z][\w.-]*(:[\w.-]+)?=/.test(trimmed)
}
