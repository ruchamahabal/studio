import { pinia } from "../support/component"

import { setActivePinia } from "pinia"
import { createRouter, createMemoryHistory } from "vue-router"
// @ts-ignore
import { resourcesPlugin } from "frappe-ui"
import { spritePlugin } from "frappe-ui/icons"

import StudioCanvas from "@/components/StudioCanvas.vue"
import Block from "@/utils/block"
import { COMPONENTS } from "@/data/components"
import { getBlockInstance, getComponentBlock } from "@/utils/serializer"
import getBlockTemplate from "@/utils/blockTemplate"
import { registerGlobalComponents } from "@/globals"
import useCanvasStore from "@/stores/canvasStore"

describe("scoped slot props", () => {
	let canvas: any

	beforeEach(() => {
		Block.setComponents(COMPONENTS)
		setActivePinia(pinia)
		const router = createRouter({
			history: createMemoryHistory(),
			routes: [{ path: "/", component: { template: "<div />" } }],
		})

		cy.viewport(1440, 900)
		cy.mount(StudioCanvas as any, {
			props: { componentTree: getBlockInstance(getBlockTemplate("body")) },
			global: {
				plugins: [pinia, router, resourcesPlugin, spritePlugin, { install: registerGlobalComponents }],
			},
		}).then(({ wrapper }) => {
			canvas = wrapper.vm
			useCanvasStore().activeCanvas = canvas
		})
	})

	it("resolves a scoped slot prop in an expression on a block inside the slot", () => {
		// Tabs exposes { tab } to its tab-panel slot
		let text: Block

		cy.then(() => {
			const tabs = canvas.rootComponent.addChild(getComponentBlock("Tabs"))
			tabs.addSlot("tab-panel")
			text = tabs.updateSlot("tab-panel", getComponentBlock("TextBlock")) as Block
			text.setProp("text", "{{ tab.label }}")
		})

		cy.then(() => {
			cy.get(`[data-component-id="${text.componentId}"]`).first().should("have.text", "Github")
		})
	})

	it("exposes the scope to autocompletions once a block inside the slot is clicked", () => {
		let text: Block

		cy.then(() => {
			const tabs = canvas.rootComponent.addChild(getComponentBlock("Tabs"))
			tabs.addSlot("tab-panel")
			text = tabs.updateSlot("tab-panel", getComponentBlock("TextBlock")) as Block
			canvas.clearSelection()
		})

		cy.then(() => {
			cy.get(`[data-component-id="${text.componentId}"]`).first().click({ force: true })
		})

		cy.then(() => {
			expect(text.getCompletions().map((source) => source.completion.label)).to.include("tab")
		})
	})
})
