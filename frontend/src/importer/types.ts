// Manifest types produced by the Vue -> Studio importer.
// The manifest is a plain-JSON description of a Studio App and its pages that
// the Python ingest command (studio/studio/importer/ingest.py) turns into
// Studio App / Studio Page DocTypes.

export interface ManifestBlock {
	componentId: string
	componentName: string
	blockName?: string
	originalElement?: string
	isCustomVueComponent?: boolean
	visibilityCondition?: string
	componentProps?: Record<string, any>
	componentEvents?: Record<string, any>
	componentSlots?: Record<string, { slotName: string; slotContent: ManifestBlock[] }>
	baseStyles?: Record<string, any>
	children?: ManifestBlock[]
	classes?: string[]
}

export interface ManifestResource {
	resource_name: string
	resource_type: "Document List" | "Document" | "API Resource"
	document_type?: string
	document_name?: string
	fetch_document_using_filters?: 0 | 1
	fields?: string
	filters?: string
	limit?: number
	url?: string
	method?: string
	transform?: string
	on_success?: string
	on_error?: string
	auto?: 0 | 1
}

export interface ManifestVariable {
	variable_name: string
	variable_type: "String" | "Number" | "Boolean" | "Object"
	initial_value: string
}

export interface ManifestWatcher {
	source: string
	script: string
	immediate?: 0 | 1
	deep?: 0 | 1
}

export interface ManifestClientScript {
	// becomes a "Studio Client Script" doc linked to the page
	name_hint: string
	script: string
}

export interface ManifestPage {
	page_title: string
	route: string
	blocks: ManifestBlock[]
	resources: ManifestResource[]
	variables: ManifestVariable[]
	watchers: ManifestWatcher[]
	client_scripts: ManifestClientScript[]
}

export interface CustomComponentRecord {
	component_name: string
	source_path: string // resolved path in the CRM frontend
	dest_path: string // where it was copied under <app>/studio/<studio_app>
	copied: boolean
	note?: string
}

export interface ImportNote {
	page: string
	kind: "store-dropped" | "custom-wrapped" | "unsupported" | "info"
	detail: string
}

export interface Manifest {
	app_name: string
	app_title: string
	frappe_app: string
	pages: ManifestPage[]
	custom_components: CustomComponentRecord[]
	report: ImportNote[]
}

// Local import collected from a <script setup> block: maps a local identifier
// (component or value) to its import source string.
export type ImportMap = Record<string, string>
