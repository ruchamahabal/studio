import { computed } from "vue"
import type Block from "@/utils/block"
import { expandBlock } from "@/utils/blockCodec"
import useCanvasStore from "@/stores/canvasStore"
import useStudioStore from "@/stores/studioStore"

export type AgentOperation = {
	tool_name: "update_block" | "add_block" | "remove_block" | "move_block"
	args: Record<string, any>
}

export function useAIChatController() {
	const store = useStudioStore()
	const canvasStore = useCanvasStore()

	const selectedBlock = computed<Block | null>(() => {
		const block = canvasStore.activeCanvas?.selectedBlocks?.[0] ?? null
		if (!block || block.isRoot()) return null
		return block
	})

	const pageHasContent = computed(() => {
		return (canvasStore.activeCanvas?.getRootBlock()?.children?.length ?? 0) > 0
	})

	const mode = computed<"generate" | "agent" | "modify">(() => {
		if (selectedBlock.value) return "modify"
		if (pageHasContent.value) return "agent"
		return "generate"
	})

	function applyOperation(op: AgentOperation) {
		const canvas = canvasStore.activeCanvas
		if (!canvas) return
		try {
			switch (op.tool_name) {
				case "update_block":
					_applyUpdateBlock(canvas, op.args)
					break
				case "add_block":
					_applyAddBlock(canvas, op.args)
					break
				case "remove_block":
					_applyRemoveBlock(canvas, op.args)
					break
				case "move_block":
					_applyMoveBlock(canvas, op.args)
					break
			}
		} catch (e) {
			console.warn(`[AI Agent] Failed to apply ${op.tool_name}:`, e)
		}
	}

	function _applyUpdateBlock(canvas: any, args: Record<string, any>) {
		const block = canvas.findBlock(args.component_id) as Block | null
		if (!block) return
		if (args.base_styles) {
			Object.entries(args.base_styles).forEach(([k, v]) => block.setBaseStyle(k as any, v as any))
		}
		if (args.mobile_styles) Object.assign(block.mobileStyles, args.mobile_styles)
		if (args.tablet_styles) Object.assign(block.tabletStyles, args.tablet_styles)
		if (args.component_props) {
			Object.entries(args.component_props).forEach(([k, v]) => block.setProp(k, v))
		}
		if (args.attributes) block.setAttributes(args.attributes)
	}

	function _applyAddBlock(canvas: any, args: Record<string, any>) {
		const parent = canvas.findBlock(args.parent_component_id) as Block | null
		if (!parent) return
		const blockDef = expandBlock(args.block)
		if (args.after_component_id) {
			const sibling = canvas.findBlock(args.after_component_id) as Block | null
			if (sibling) {
				parent.addChildAfter(blockDef, sibling)
				return
			}
		}
		parent.addChild(blockDef, args.index ?? null)
	}

	function _applyRemoveBlock(canvas: any, args: Record<string, any>) {
		const block = canvas.findBlock(args.component_id) as Block | null
		if (!block) return
		block.getParentBlock()?.removeChild(block)
	}

	function _applyMoveBlock(canvas: any, args: Record<string, any>) {
		const block = canvas.findBlock(args.component_id) as Block | null
		const newParent = canvas.findBlock(args.new_parent_component_id) as Block | null
		if (!block || !newParent) return

		const oldParent = block.getParentBlock()
		if (oldParent) {
			const idx = oldParent.children.indexOf(block)
			if (idx !== -1) oldParent.children.splice(idx, 1)
		}
		block.parentBlock = newParent

		if (args.after_component_id) {
			const sibIdx = newParent.children.findIndex((c: Block) => c.componentId === args.after_component_id)
			if (sibIdx !== -1) {
				newParent.children.splice(sibIdx + 1, 0, block)
				return
			}
		}
		const insertAt = args.index != null ? args.index : newParent.children.length
		newParent.children.splice(Math.max(0, Math.min(insertAt, newParent.children.length)), 0, block)
	}

	return { mode, selectedBlock, pageHasContent, applyOperation, store, canvasStore }
}
