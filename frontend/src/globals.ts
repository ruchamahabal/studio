import { App, defineAsyncComponent } from "vue"
import {
	Alert,
	Autocomplete,
	Avatar,
	Badge,
	Breadcrumbs,
	Button,
	Card,
	Checkbox,
	Combobox,
	DatePicker,
	TimePicker,
	DateTimePicker,
	DateRangePicker,
	Dialog,
	Divider,
	Dropdown,
	MonthPicker,
	ErrorMessage,
	FeatherIcon,
	FileUploader,
	FormControl,
	FormLabel,
	Input,
	ListItem,
	ListView,
	LoadingIndicator,
	LoadingText,
	MultiSelect,
	Progress,
	Popover,
	Rating,
	Select,
	Sidebar,
	Switch,
	TabButtons,
	Tabs,
	TextInput,
	Textarea,
	TextEditor,
	Toast,
	Tooltip,
	Tree,
	CommandPalette,
	CommandPaletteItem,
	Calendar,
	NumberChart,
	AxisChart,
	DonutChart,
} from "frappe-ui"
import { Filter, Link } from "frappe-ui/frappe"

import Container from "@/components/AppLayout/Container.vue"
import FitContainer from "@/components/AppLayout/FitContainer.vue"
import SplitView from "@/components/AppLayout/SplitView.vue"
import Repeater from "@/components/AppLayout/Repeater.vue"
import HTML from "@/components/AppLayout/HTML.vue"
import CardList from "@/components/AppLayout/CardList.vue"
import AvatarCard from "@/components/AppLayout/AvatarCard.vue"
import Audio from "@/components/AppLayout/Audio.vue"
import ImageView from "@/components/AppLayout/ImageView.vue"
import TextBlock from "@/components/AppLayout/TextBlock.vue"
import AppHeader from "@/components/AppLayout/AppHeader.vue"
import BottomTabs from "@/components/AppLayout/BottomTabs.vue"
import MarkdownEditor from "@/components/AppLayout/MarkdownEditor.vue"

import { vueComponents } from "@/data/vueComponents"
import { default as componentRegistry } from "@/data/components"
import { default as Block } from "@/utils/block"
import componentBarrels from "virtual:custom-components"

export function registerGlobalComponents(app: App) {
	app.component("Alert", Alert)
	app.component("Autocomplete", Autocomplete)
	app.component("Avatar", Avatar)
	app.component("Badge", Badge)
	app.component("Breadcrumbs", Breadcrumbs)
	app.component("Button", Button)
	app.component("Card", Card)
	app.component("Checkbox", Checkbox)
	app.component("Combobox", Combobox)
	app.component("DatePicker", DatePicker)
	app.component("TimePicker", TimePicker)
	app.component("DateTimePicker", DateTimePicker)
	app.component("DateRangePicker", DateRangePicker)
	app.component("MonthPicker", MonthPicker)
	app.component("Dialog", Dialog)
	app.component("Divider", Divider)
	app.component("Dropdown", Dropdown)
	app.component("ErrorMessage", ErrorMessage)
	app.component("FeatherIcon", FeatherIcon)
	app.component("FileUploader", FileUploader)
	app.component("Filter", Filter)
	app.component("FormControl", FormControl)
	app.component("FormLabel", FormLabel)
	app.component("Input", Input)
	app.component("Link", Link)
	app.component("ListItem", ListItem)
	app.component("ListView", ListView)
	app.component("LoadingIndicator", LoadingIndicator)
	app.component("LoadingText", LoadingText)
	app.component("MultiSelect", MultiSelect)
	app.component("Progress", Progress)
	app.component("Popover", Popover)
	app.component("Rating", Rating)
	app.component("Select", Select)
	app.component("Sidebar", Sidebar)
	app.component("Switch", Switch)
	app.component("TabButtons", TabButtons)
	app.component("Tabs", Tabs)
	app.component("TextInput", TextInput)
	app.component("Textarea", Textarea)
	app.component("TextEditor", TextEditor)
	app.component("Toast", Toast)
	app.component("Tooltip", Tooltip)
	app.component("Tree", Tree)
	app.component("CommandPalette", CommandPalette)
	app.component("CommandPaletteItem", CommandPaletteItem)
	app.component("Calendar", Calendar)
	app.component("NumberChart", NumberChart)
	app.component("AxisChart", AxisChart)
	app.component("DonutChart", DonutChart)

	// studio components
	app.component("Container", Container)
	app.component("FitContainer", FitContainer)
	app.component("SplitView", SplitView)
	app.component("Repeater", Repeater)
	app.component("HTML", HTML)
	app.component("CardList", CardList)
	app.component("AvatarCard", AvatarCard)
	app.component("Audio", Audio)
	app.component("ImageView", ImageView)
	app.component("TextBlock", TextBlock)
	app.component("AppHeader", AppHeader)
	app.component("BottomTabs", BottomTabs)
	app.component("MarkdownEditor", MarkdownEditor)
}

export interface CustomVueComponentMeta {
	component_name: string
	frappe_app: string
	studio_app: string
	file_path: string
}

/**
 * Dynamically register custom Vue components from a specific Frappe app into the Vue app instance.
 * Also registers them in the component data registry so Block class can access their metadata.
 * Returns the list of registered component metadata for use in the ComponentPanel.
 *
 * @param app - The Vue app instance
 * @param frappeApp - The Frappe app name to fetch components for
 */
export async function registerCustomVueComponents(app: App, frappeApp: string): Promise<CustomVueComponentMeta[]> {
	try {
		if (!frappeApp) return []
		const components: CustomVueComponentMeta[] = await vueComponents.reload({ frappe_app: frappeApp })

		// Load all barrel modules upfront — each barrel is keyed by "{appName}/{studioApp}"
		const loadedModules: Record<string, Record<string, any>> = {}
		for (const [barrelKey, loader] of Object.entries(componentBarrels)) {
			// Only load barrels belonging to the active frappe app
			if (!barrelKey.startsWith(`${frappeApp}/`)) continue
			try {
				loadedModules[barrelKey] = await loader()
			} catch (err) {
				console.error(`Failed to load component barrel "${barrelKey}":`, err)
			}
		}

		for (const comp of components) {
			try {
				// Look up the component in loaded barrel modules
				const barrelKey = `${comp.frappe_app}/${comp.studio_app}`
				const barrelModule = loadedModules[barrelKey]
				const componentDef = barrelModule?.[comp.component_name]

				if (componentDef) {
					app.component(comp.component_name, componentDef)
				} else if (import.meta.env.DEV) {
					// Dev-only fallback for components not yet in a barrel file
					app.component(
						comp.component_name,
						defineAsyncComponent(() => import(/* @vite-ignore */ comp.file_path)),
					)
				} else {
					console.warn(
						`Custom component "${comp.component_name}" was not found in the build. ` +
							`Ensure it is exported from a components.js barrel file and run \`bench build\`.`,
					)
					continue
				}

				// Register in the component data registry for Block metadata access
				componentRegistry.registerCustomVueComponent(comp.component_name, comp.frappe_app)
			} catch (err) {
				console.error(`Failed to load custom component ${comp.component_name}:`, err)
			}
		}

		window.__APP_COMPONENTS__ = app._context.components
		const { COMPONENTS } = await import("@/data/components")
		Block.setComponents(COMPONENTS)

		return components
	} catch (err) {
		console.error("Failed to fetch custom Vue components:", err)
		return []
	}
}

/**
 * Unregister previously registered custom Vue components from the Vue app instance.
 * Called when switching apps to clean up components from the previous app's frappe_app.
 */
export function unregisterCustomVueComponents(app: App, components: CustomVueComponentMeta[]) {
	for (const comp of components) {
		delete app._context.components[comp.component_name]
		componentRegistry.unregisterCustomVueComponent(comp.component_name)
	}

	window.__APP_COMPONENTS__ = app._context.components
	Block.setComponents(componentRegistry.getComponents())
}

