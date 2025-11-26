export interface StudioComponent {
	name: string
	component_id: string
	component_name: string
	/**	Block : JSON	*/
	block?: any
	props?: StudioComponentProp[]
	creation?: string
	modified?: string
}

export interface StudioComponentProp {
	prop: string
	type: string
	description?: string
	default?: string
	required?: number
	options?: string // For select type
}

// for UI
export interface ComponentPropUI {
	prop: string
	type: string
	description?: string
	default?: string
	options?: string // For select type
	required?: number
	showPopover?: boolean
	inputControl?: any
	inputType?: string
}