declare module "virtual:custom-components" {
	/**
	 * Map of barrel keys ("{appName}/{studioApp}") to lazy loaders.
	 * Each loader returns a module whose named exports are Vue components.
	 *
	 * Example:
	 *   const barrels = await componentBarrels["mini_pos/testing"]()
	 *   // barrels.EmojiCard, barrels.ProductCard, etc.
	 */
	const componentBarrels: Record<string, () => Promise<Record<string, any>>>
	export default componentBarrels
}
