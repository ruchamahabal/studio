declare module "frappe-ui";
declare module "frappe-ui/tailwind/tokens.js";

// moduleResolution "node" can't read the package `exports` subpath map, so point the
// /menus subpath (BubbleMenu, FloatingMenu) at its real type declarations.
declare module "@tiptap/vue-3/menus" {
	export * from "@tiptap/vue-3/dist/menus/index";
}

// Build-time flag: true when apps/frappe/ui (@framework/ui) exists on this bench.
// Injected by vite `define`; gates @framework/ui registration and panel visibility.
declare const __FRAMEWORK_UI_AVAILABLE__: boolean;
