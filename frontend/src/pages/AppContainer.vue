<template>
	<AppComponent v-if="rootBlock" :block="rootBlock" />
</template>

<script setup lang="ts">
import { watch, ref, inject, onBeforeUnmount } from "vue"
import { useRoute } from "vue-router"
import { useDebounceFn } from "@vueuse/core"
import { usePageMeta } from "frappe-ui"

import { findPageWithRoute } from "@/utils/helpers"
import { getBlockInstance } from "@/utils/serializer"
import AppComponent from "@/components/AppComponent.vue"

import useAppStore from "@/stores/appStore"
import useCodeStore from "@/stores/codeStore"

import type { StudioPage } from "@/types/Studio/StudioPage"
import Block from "@/utils/block"

const store = useAppStore()
const route = useRoute()
const codeStore = useCodeStore()
const page = ref<StudioPage | null>(null)

const rootBlock = ref<Block | null>(null)

// live-reload the preview when the page it shows is edited in the studio (draft autosave / publish)
const socket = inject<any>("socket")
let subscribedEvent: string | null = null

async function loadPage() {
	let { pageRoute } = route.params as { pageRoute: string[] }
	const isDynamic = route.meta?.isDynamic

	let currentPath = "/"
	if (isDynamic) {
		currentPath = route.matched?.[0]?.path
	} else if (pageRoute) {
		currentPath = pageRoute[0]
	}

	if (!currentPath) {
		rootBlock.value = null
		return
	}

	page.value = await findPageWithRoute(window.app_name, currentPath)
	if (!page.value) return
	await store.setPageData(page.value)
	await codeStore.setPageScript(page.value, Boolean(page.value.is_standard))

	const blocks = window.is_preview
		? JSON.parse(page.value?.draft_blocks || page.value?.blocks)
		: JSON.parse(page.value?.blocks)
	if (blocks) {
		rootBlock.value = getBlockInstance(blocks[0])
	}

	subscribeToPageUpdates()
}

// debounced so a burst of canvas autosaves reloads the preview once, not per keystroke
const reloadPage = useDebounceFn(loadPage, 300)

watch(() => route.path, loadPage, { immediate: true })

// only the editor preview needs live reload; a published app is served to end users as-is
function subscribeToPageUpdates() {
	if (!socket || !window.is_preview || !page.value) return
	const event = `studio_page_update_${page.value.name}`
	if (event === subscribedEvent) return
	unsubscribeFromPageUpdates()
	subscribedEvent = event
	socket.on(event, reloadPage)
}

function unsubscribeFromPageUpdates() {
	if (socket && subscribedEvent) {
		socket.off(subscribedEvent, reloadPage)
		subscribedEvent = null
	}
}

onBeforeUnmount(unsubscribeFromPageUpdates)

usePageMeta(() => {
	return {
		title: page.value?.page_title,
	}
})
</script>
