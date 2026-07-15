<template>
	<div>
		<slot name="empty" v-if="!data?.length">
			<div
				class="pointer-events-none flex h-full w-full items-center justify-center p-5 text-base text-ink-gray-6"
			>
				{{ emptyStateMessage || "No data" }}
			</div>
		</slot>
		<div class="flex flex-row flex-wrap gap-5" v-else v-bind="$attrs">
			<template v-for="(dataItem, dataIndex) in data" :key="dataItem?.[dataKey] || dataIndex">
				<RepeaterContextProvider :dataItem="dataItem" :dataIndex="dataIndex" :dataKey="dataKey">
					<slot v-bind="{ dataItem, dataKey, dataIndex }"></slot>
				</RepeaterContextProvider>
			</template>
		</div>
	</div>
</template>

<script setup lang="ts">
import RepeaterContextProvider from "@/components/AppLayout/RepeaterContextProvider.vue"
import type { RepeaterProps } from "@/types/studio_components/Repeater"

defineProps<RepeaterProps>()
defineOptions({ inheritAttrs: false })
</script>
