"""Server-side APPLICATION of the agent's block ops for one turn.

The loop applies each client block op to this tree and persists the result to
the target page's draft — the DB is the source of truth for agent writes, the
way a file on disk is for a code agent. The editor canvas mirrors the same ops
live only while it is showing the target page; navigating away can therefore
never redirect a write (the op is addressed to a page, not to "whatever is
open"), and a closed tab never loses one.

Applying here also keeps the tool result honest: "applied to block X",
"3 of 12 not found", "parent not found" — instead of a blanket "Applied." that
hides a silently dropped edit. A wrong ref drives a self-correcting round.

Mutation semantics mirror the frontend ToolDispatcher exactly (shallow merges,
insertion order, slot shapes) so the live canvas and the persisted draft can't
drift. New blocks get their ids HERE (BlockCodec.ensure_ids), echoed back into
the op args so the canvas builds the same ids the draft stores.
"""

from studio.ai.agent.selectors import child_blocks, find_block, walk_blocks
from studio.ai.block_codec import BlockCodec


def wrap_expression(expression) -> str:
	"""Wrap a raw expression in `{{ }}` unless it already is a dynamic value
	(mirrors the frontend's isDynamicValue)."""
	expr = str(expression if expression is not None else "")
	if "{{" in expr and "}}" in expr:
		return expr
	return f"{{{{ {expr.strip()} }}}}"


def stamp_compact_ids(compact: dict, expanded: dict) -> None:
	"""Echo the ids assigned on the expanded tree back into the compact op args,
	so the canvas (which re-expands the args) builds the same ids the draft stores.
	Walks both shapes in parallel — expand() maps c→children and slots→slotContent
	one to one (non-dict entries filtered on both sides)."""
	compact["id"] = expanded.get("componentId")
	compact_children = [c for c in (compact.get("c") or []) if isinstance(c, dict)]
	for c_child, e_child in zip(compact_children, expanded.get("children") or [], strict=False):
		stamp_compact_ids(c_child, e_child)
	expanded_slots = expanded.get("componentSlots") or {}
	for name, content in (compact.get("slots") or {}).items():
		if not isinstance(content, list):
			continue
		slot_children = [c for c in content if isinstance(c, dict)]
		expanded_content = (expanded_slots.get(name) or {}).get("slotContent") or []
		for c_child, e_child in zip(slot_children, expanded_content, strict=False):
			stamp_compact_ids(c_child, e_child)


class WorkingTree:
	def __init__(self, root: dict | None):
		self.root = root

	def resolve(self, component_id: str | None) -> dict | None:
		return find_block(self.root, component_id) if (self.root and component_id) else None

	def parent_of(self, component_id: str) -> dict | None:
		for block, _ in walk_blocks(self.root):
			for child in child_blocks(block):
				if child.get("componentId") == component_id:
					return block
		return None

	def detach(self, component_id: str) -> None:
		"""Remove the block from its parent — whether it sits in `children` or in a named slot."""
		parent = self.parent_of(component_id)
		if parent is None:
			return
		if parent.get("children"):
			parent["children"] = [c for c in parent["children"] if c.get("componentId") != component_id]
		for slot in (parent.get("componentSlots") or {}).values():
			content = slot.get("slotContent") if isinstance(slot, dict) else None
			if isinstance(content, list):
				slot["slotContent"] = [c for c in content if c.get("componentId") != component_id]

	def id_hint(self, component_id: str | None) -> str:
		"""The model often passes a block's HTML id (attributes.id) instead of its
		editor ref — the most common miss. When the id matches a real block, name its
		ref."""
		for block, _ in walk_blocks(self.root or {}):
			attrs = block.get("attributes") or {}
			if component_id and attrs.get("id") == component_id:
				return (
					f" — that's the HTML id; this block's ref is '{block.get('componentId')}'. Use the ref."
				)
		return " — not a valid ref. Call query_blocks or re-read the page outline for real refs."

	def apply(self, tool_name: str, args: dict) -> str:
		args = args or {}
		if tool_name == "update_block":
			return self.apply_update(args)
		if tool_name == "update_blocks":
			return self.apply_update_blocks(args)
		if tool_name == "remove_block":
			return self.apply_remove(args.get("component_id"))
		if tool_name == "move_block":
			return self.apply_move(args)
		if tool_name == "add_block":
			return self.apply_add(args)
		if tool_name == "set_slot":
			return self.apply_set_slot(args)
		if tool_name == "remove_slot":
			return self.apply_remove_slot(args)
		if tool_name in ("bind_prop", "set_repeater_data", "sync_variable"):
			return self.apply_bind(tool_name, args)
		if tool_name in ("set_event_handler", "set_visibility"):
			return self.apply_interactivity(tool_name, args)
		# Unknown client tools pass through (nothing to mirror or persist).
		return "Applied."

	def apply_update(self, args: dict) -> str:
		component_id = args.get("component_id")
		block = self.resolve(component_id)
		if block is None:
			return f"FAILED: component_id '{component_id}' not found{self.id_hint(component_id)}"
		self.merge_patch(block, args)
		return f"Applied to block {component_id} (<{block.get('componentName') or 'div'}>)."

	def apply_update_blocks(self, args: dict) -> str:
		patches = args.get("patches")
		if isinstance(patches, list):
			pairs = [(p.get("component_id"), p) for p in patches if isinstance(p, dict)]
		else:
			pairs = [(i, args) for i in (args.get("component_ids") or [])]
		if not pairs:
			return "FAILED: no component_ids or patches supplied — nothing to update."
		missing = []
		for component_id, patch in pairs:
			block = self.resolve(component_id)
			if block is None:
				missing.append(component_id)
			else:
				self.merge_patch(block, patch)
		applied = len(pairs) - len(missing)
		if missing:
			return (
				f"Applied to {applied} of {len(pairs)} blocks. NOT FOUND: {missing}. "
				"Those refs don't exist — recheck them, don't reissue the same ids."
			)
		return f"Applied to all {applied} block(s)."

	def merge_patch(self, block: dict, args: dict) -> None:
		"""Shallow-merge one block's changes — the same semantics as the canvas
		(setProp/setBaseStyle per key, Object.assign for responsive overrides)."""
		if props := args.get("props"):
			block.setdefault("componentProps", {}).update(props)
		if style := args.get("style"):
			block.setdefault("baseStyles", {}).update(style)
		if mstyle := args.get("mstyle"):
			block.setdefault("mobileStyles", {}).update(mstyle)
		if tstyle := args.get("tstyle"):
			block.setdefault("tabletStyles", {}).update(tstyle)
		if args.get("label") is not None:
			block["blockName"] = args["label"]

	def apply_remove(self, component_id: str | None) -> str:
		block = self.resolve(component_id)
		if block is None:
			return f"FAILED: component_id '{component_id}' not found{self.id_hint(component_id)}"
		self.detach(component_id)
		return f"Removed block {component_id}."

	def apply_move(self, args: dict) -> str:
		component_id = args.get("component_id")
		new_parent_id = args.get("new_parent_component_id")
		block = self.resolve(component_id)
		if block is None:
			return f"FAILED: component_id '{component_id}' not found{self.id_hint(component_id)}"
		new_parent = self.resolve(new_parent_id)
		if new_parent is None:
			return f"FAILED: new_parent_component_id '{new_parent_id}' not found{self.id_hint(new_parent_id)}"
		# A block can't become a child of itself or its own descendant — that would
		# cycle the tree (and infinite-loop a later walk). Reject it like an invalid ref.
		if find_block(block, new_parent_id) is not None:
			return f"FAILED: can't move {component_id} into itself or its own descendant ({new_parent_id})."
		self.detach(component_id)
		self.insert_child(new_parent, block, args)
		return f"Moved block {component_id} under {new_parent_id}."

	def apply_add(self, args: dict) -> str:
		parent_id = args.get("parent_component_id")
		parent = self.resolve(parent_id)
		if parent is None:
			return f"FAILED: parent_component_id '{parent_id}' not found{self.id_hint(parent_id)}"
		compact = args.get("block") or {}
		block = BlockCodec.ensure_ids(BlockCodec.expand(compact))
		# Echo the assigned ids into the op args so the canvas builds the same ids.
		if isinstance(compact, dict):
			stamp_compact_ids(compact, block)
		args["component_id"] = block.get("componentId")
		self.insert_child(parent, block, args)
		name = block.get("componentName") or "block"
		return f"Added the {name} block under {parent_id} (its id is {block['componentId']})."

	def insert_child(self, parent: dict, block: dict, args: dict) -> None:
		"""Place `block` in `parent` honoring after_component_id > index > append —
		the same precedence the canvas uses. A sibling found inside a named slot
		places the block in that slot's content."""
		after_id = args.get("after_component_id")
		if after_id:
			for siblings in self.child_lists(parent):
				for i, sibling in enumerate(siblings):
					if sibling.get("componentId") == after_id:
						siblings.insert(i + 1, block)
						return
		children = parent.setdefault("children", [])
		index = args.get("index")
		if isinstance(index, int) and 0 <= index <= len(children):
			children.insert(index, block)
		else:
			children.append(block)

	@staticmethod
	def child_lists(parent: dict) -> list[list]:
		"""Every list that can hold `parent`'s children: `children` plus each named
		slot's content."""
		lists = []
		if isinstance(parent.get("children"), list):
			lists.append(parent["children"])
		for slot in (parent.get("componentSlots") or {}).values():
			content = slot.get("slotContent") if isinstance(slot, dict) else None
			if isinstance(content, list):
				lists.append(content)
		return lists

	def apply_set_slot(self, args: dict) -> str:
		"""Replace a NAMED slot's content with the given blocks (ids assigned here,
		echoed back into the args for the canvas)."""
		component_id = args.get("component_id")
		block = self.resolve(component_id)
		if block is None:
			return f"FAILED: component_id '{component_id}' not found{self.id_hint(component_id)}"
		slot_name = args.get("slot_name")
		blocks_arg = args.get("blocks")
		if not slot_name or not isinstance(blocks_arg, list):
			return "FAILED: set_slot needs slot_name and a blocks list."
		content = []
		for child in blocks_arg:
			if not isinstance(child, dict):
				continue
			expanded = BlockCodec.ensure_ids(BlockCodec.expand(child))
			stamp_compact_ids(child, expanded)
			content.append(expanded)
		block.setdefault("componentSlots", {})[slot_name] = {
			"slotName": slot_name,
			"slotContent": content,
		}
		return f"Set the '{slot_name}' slot of block {component_id}."

	def apply_remove_slot(self, args: dict) -> str:
		component_id = args.get("component_id")
		block = self.resolve(component_id)
		if block is None:
			return f"FAILED: component_id '{component_id}' not found{self.id_hint(component_id)}"
		slot_name = args.get("slot_name")
		if isinstance(block.get("componentSlots"), dict):
			block["componentSlots"].pop(slot_name, None)
		return f"Removed the '{slot_name}' slot from block {component_id}."

	def apply_bind(self, tool_name: str, args: dict) -> str:
		component_id = args.get("component_id")
		block = self.resolve(component_id)
		if block is None:
			return f"FAILED: component_id '{component_id}' not found{self.id_hint(component_id)}"
		props = block.setdefault("componentProps", {})
		if tool_name == "set_repeater_data":
			source = args.get("data_source_name")
			props["data"] = f"{{{{ {source}.data }}}}"
			if args.get("data_key"):
				props["dataKey"] = args["data_key"]
			return f"Bound block {component_id} to repeat over {{{{ {source}.data }}}}."
		if tool_name == "sync_variable":
			prop = args.get("prop") or "modelValue"
			props[prop] = {"$type": "variable", "name": args.get("variable_name")}
			return (
				f"Synced {prop} of block {component_id} two-way with variable '{args.get('variable_name')}'."
			)
		if not args.get("prop"):
			return "FAILED: bind_prop needs a prop name."
		wrapped = wrap_expression(args.get("expression"))
		props[args["prop"]] = wrapped
		return f"Bound prop '{args.get('prop')}' of block {component_id} to {wrapped}."

	def apply_interactivity(self, tool_name: str, args: dict) -> str:
		component_id = args.get("component_id")
		block = self.resolve(component_id)
		if block is None:
			return f"FAILED: component_id '{component_id}' not found{self.id_hint(component_id)}"
		if tool_name == "set_event_handler":
			event, script = args.get("event"), args.get("script")
			if not event or not script:
				return "FAILED: set_event_handler needs both event and script."
			block.setdefault("componentEvents", {})[event] = {
				"event": event,
				"action": "Run Script",
				"script": script,
			}
			return f"Wired {event} handler on block {component_id}."
		if not args.get("expression"):
			return "FAILED: set_visibility needs an expression."
		wrapped = wrap_expression(args["expression"])
		block["visibilityCondition"] = wrapped
		return f"Set visibility of block {component_id} to {wrapped}."
