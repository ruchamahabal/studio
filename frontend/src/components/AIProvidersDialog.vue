<template>
	<Dialog
		v-model="show"
		:options="{ title: selected ? presetTitle : 'AI Providers', size: 'lg' }"
		@after-leave="reset"
	>
		<template #body-content>
			<!-- provider list -->
			<div v-if="!selected" class="flex flex-col">
				<p class="mb-2 text-p-xs text-ink-gray-6">
					Connect a provider to power the AI assistant. Keys stay on your site.
				</p>
				<button
					v-for="p in presets"
					:key="p.id"
					class="flex w-full items-center gap-3 rounded-md px-2.5 py-2.5 text-left hover:bg-surface-gray-2"
					@click="select(p)"
				>
					<span
						class="flex h-8 w-8 flex-none items-center justify-center rounded-md border border-outline-gray-2 text-xs font-semibold text-ink-gray-6"
					>
						{{ p.custom ? "+" : p.name.slice(0, 2) }}
					</span>
					<span class="min-w-0 flex-1">
						<span class="block truncate text-xs font-medium text-ink-gray-9">
							{{ p.custom ? "Add custom endpoint" : p.name }}
						</span>
						<span class="mt-0.5 block truncate text-[11px] text-ink-gray-5">{{ p.tagline }}</span>
					</span>
					<span v-if="p.configured" class="flex items-center gap-1 text-[11px] font-medium text-ink-green-3">
						<span class="h-1.5 w-1.5 rounded-full bg-surface-green-3" />
						Connected
					</span>
					<FeatherIcon v-else name="chevron-right" class="h-4 w-4 text-ink-gray-4" />
				</button>
			</div>

			<!-- provider detail -->
			<div v-else class="flex flex-col gap-4">
				<button
					class="flex w-fit items-center gap-1 text-xs text-ink-gray-5 hover:text-ink-gray-8"
					@click="deselect"
				>
					<FeatherIcon name="arrow-left" class="h-3.5 w-3.5" />
					All providers
				</button>

				<p class="text-p-xs text-ink-gray-6">{{ selected.blurb }}</p>

				<!-- ChatGPT sign-in (OAuth) -->
				<div v-if="selected.oauth" class="flex flex-col gap-2">
					<div
						v-if="oauthStatus === 'connected' || (selected.configured && oauthStatus === 'idle')"
						class="flex items-center gap-2 rounded-md border border-outline-gray-1 bg-surface-gray-1 px-3 py-2.5 text-xs text-ink-gray-7"
					>
						<FeatherIcon name="check-circle" class="h-4 w-4 text-ink-green-3" />
						Signed in with ChatGPT
					</div>
					<Button
						v-else-if="oauthStatus !== 'pending'"
						variant="solid"
						label="Sign in with ChatGPT"
						:loading="saving"
						@click="beginOAuth"
					/>
					<div
						v-else
						class="rounded-md border border-outline-gray-1 bg-surface-gray-1 px-3 py-2.5 text-xs text-ink-gray-7"
					>
						Waiting for sign-in…
					</div>
					<!-- popup blockers eat window.open — a plain link is the reliable path -->
					<a
						v-if="oauthUrl && oauthStatus === 'pending'"
						:href="oauthUrl"
						target="_blank"
						rel="noopener noreferrer"
						class="flex w-fit items-center gap-1.5 text-xs text-ink-gray-6 underline hover:text-ink-gray-9"
					>
						<FeatherIcon name="external-link" class="h-3 w-3" />
						Open the sign-in page
					</a>
					<button
						v-if="oauthStatus === 'pending' && !showManual"
						class="w-fit text-xs text-ink-gray-5 hover:text-ink-gray-8"
						@click="showManual = true"
					>
						Paste the redirect URL instead
					</button>
					<form
						v-if="showManual && oauthStatus === 'pending'"
						class="flex gap-2"
						@submit.prevent="completeOAuth"
					>
						<FormControl
							v-model="callbackUrl"
							type="text"
							variant="outline"
							class="flex-1"
							placeholder="http://localhost:1455/auth/callback?..."
						/>
						<Button label="Complete" :disabled="!callbackUrl.trim() || saving" @click="completeOAuth" />
					</form>
				</div>

				<!-- API key entry -->
				<div v-else class="flex flex-col gap-2">
					<ol v-if="selected.key_steps?.length && !selected.custom" class="flex flex-col gap-1">
						<li v-for="(step, i) in selected.key_steps" :key="i" class="text-[11px] text-ink-gray-5">
							{{ i + 1 }}. {{ step }}
						</li>
					</ol>
					<a
						v-if="selected.key_url"
						:href="selected.key_url"
						target="_blank"
						rel="noopener noreferrer"
						class="flex w-fit items-center gap-1 text-xs text-ink-blue-3 underline"
					>
						Get a key
						<FeatherIcon name="external-link" class="h-3 w-3" />
					</a>
					<FormControl
						v-if="selected.needs_name"
						v-model="providerName"
						label="Name"
						type="text"
						variant="outline"
						placeholder="Local Ollama"
					/>
					<FormControl
						v-if="selected.needs_api_base"
						v-model="apiBase"
						label="Base URL"
						type="text"
						variant="outline"
						placeholder="http://localhost:11434/v1"
					/>
					<FormControl
						v-model="apiKey"
						:label="selected.custom ? 'API key (optional)' : 'API key'"
						type="password"
						variant="outline"
						autocomplete="off"
						:placeholder="selected.has_key ? 'Using the stored key — paste to replace' : keyPlaceholder"
					/>
				</div>

				<!-- model selection -->
				<div v-if="selected.models?.length" class="flex flex-col gap-1">
					<span class="text-xs font-medium text-ink-gray-7">Models to enable</span>
					<button
						v-for="m in selected.models"
						:key="m.model_id"
						class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-surface-gray-2"
						@click="toggleModel(m.model_id)"
					>
						<FeatherIcon
							:name="chosenModels.includes(m.model_id) ? 'check-square' : 'square'"
							class="h-3.5 w-3.5 flex-none"
							:class="chosenModels.includes(m.model_id) ? 'text-ink-gray-8' : 'text-ink-gray-4'"
						/>
						<span class="min-w-0 flex-1">
							<span class="block truncate text-xs text-ink-gray-8">{{ m.label }}</span>
							<span class="block truncate text-[11px] text-ink-gray-5">{{ m.note }}</span>
						</span>
					</button>
				</div>
				<FormControl
					v-if="selected.custom"
					v-model="customModelIds"
					label="Model ids"
					type="textarea"
					variant="outline"
					placeholder="llama3.2&#10;qwen2.5"
				/>
				<p v-if="selected.custom" class="-mt-2 text-[11px] text-ink-gray-5">
					One per line — or connect first and use "Import models" to ask the endpoint.
				</p>

				<ErrorMessage v-if="verifyMessage" :message="verifyMessage" />

				<div class="flex items-center gap-2">
					<Button
						variant="solid"
						:label="connectLabel"
						:loading="saving"
						:disabled="!canConnect"
						@click="connect"
					/>
					<Button
						v-if="selected.configured && (selected.custom || selected.api_base)"
						variant="outline"
						label="Import models"
						:loading="importing"
						@click="importModels"
					/>
				</div>
			</div>
		</template>
	</Dialog>
</template>

<script lang="ts" setup>
import { ref, computed, watch, onBeforeUnmount } from "vue"
import { Dialog, Button, FormControl, ErrorMessage, FeatherIcon, call, toast } from "frappe-ui"

const show = defineModel<boolean>()
const emit = defineEmits(["changed"])

const presets = ref<any[]>([])
const selected = ref<any>(null)
const apiKey = ref("")
const providerName = ref("")
const apiBase = ref("")
const customModelIds = ref("")
const chosenModels = ref<string[]>([])
const verifyMessage = ref("")
const saving = ref(false)
const importing = ref(false)

const oauthStatus = ref("idle")
const oauthUrl = ref("")
const showManual = ref(false)
const callbackUrl = ref("")
let pollTimer: ReturnType<typeof setInterval> | null = null

const presetTitle = computed(() => selected.value?.name || "Custom endpoint")
const keyPlaceholder = computed(() =>
	selected.value?.key_prefix ? `${selected.value.key_prefix}...` : "Paste your API key",
)

const connectLabel = computed(() => {
	if (selected.value?.oauth) return `Enable ${chosenModels.value.length} model(s)`
	if (selected.value?.custom) return "Add endpoint"
	return selected.value?.configured ? "Update & verify" : "Verify & connect"
})

const canConnect = computed(() => {
	const p = selected.value
	if (!p) return false
	if (p.oauth) return (p.configured || oauthStatus.value === "connected") && chosenModels.value.length > 0
	if (p.custom) return !!providerName.value.trim() && !!apiBase.value.trim()
	if (!chosenModels.value.length) return false
	return !!apiKey.value.trim() || p.has_key
})

async function reload() {
	try {
		const state: any = await call("studio.ai.setup.ai_setup_state")
		presets.value = state?.presets ?? []
		if (selected.value) {
			selected.value = presets.value.find((p) => p.id === selected.value.id) ?? null
		}
	} catch (e: any) {
		toast.error(e?.message || "Could not load providers")
	}
}

watch(show, (open) => open && reload())

function select(p: any) {
	stopPolling()
	selected.value = p
	apiKey.value = ""
	providerName.value = ""
	apiBase.value = p.api_base || ""
	customModelIds.value = ""
	verifyMessage.value = ""
	oauthStatus.value = "idle"
	oauthUrl.value = ""
	showManual.value = false
	callbackUrl.value = ""
	chosenModels.value = (p.models ?? []).filter((m: any) => m.recommended).map((m: any) => m.model_id)
}

function deselect() {
	stopPolling()
	selected.value = null
	verifyMessage.value = ""
}

function reset() {
	deselect()
}

function toggleModel(id: string) {
	chosenModels.value = chosenModels.value.includes(id)
		? chosenModels.value.filter((m) => m !== id)
		: [...chosenModels.value, id]
}

async function connect() {
	const p = selected.value
	const models = p.custom ? parseCustomModels() : chosenModels.value
	if (p.custom && !models.length) {
		verifyMessage.value = "List at least one model id — or connect it in desk and use Import models."
		return
	}
	saving.value = true
	verifyMessage.value = ""
	try {
		// OAuth carries its own credential; a stored key is re-verified server-side when empty.
		if (!p.oauth) {
			const verdict: any = await call("studio.ai.setup.verify_ai_key", {
				preset: p.id,
				api_key: apiKey.value.trim(),
				api_base: apiBase.value.trim(),
				model_id: p.custom ? models[0] || "" : "",
			})
			if (verdict?.severity === "error") {
				verifyMessage.value = verdict.message
				return
			}
			if (verdict?.severity === "warn") toast.warning(verdict.message)
		}
		await call("studio.ai.setup.setup_ai_provider", {
			preset: p.id,
			api_key: apiKey.value.trim(),
			api_base: apiBase.value.trim(),
			models,
			provider_name: providerName.value.trim(),
		})
		toast.success(`${p.name || providerName.value} connected`)
		apiKey.value = ""
		await reload()
		emit("changed")
	} catch (e: any) {
		verifyMessage.value = e?.message || "Could not save the provider"
	} finally {
		saving.value = false
	}
}

function parseCustomModels(): string[] {
	return customModelIds.value
		.split(/[\n,]/)
		.map((m) => m.trim())
		.filter(Boolean)
}

async function importModels() {
	const p = selected.value
	importing.value = true
	try {
		const providerDocname = p.custom ? providerName.value.trim() || p.name : p.name
		const res: any = await call("studio.ai.setup.import_provider_models", { provider: providerDocname })
		toast.success(`Imported ${res?.added?.length ?? 0} model(s)`)
		emit("changed")
	} catch (e: any) {
		toast.error(e?.message || "Import failed")
	} finally {
		importing.value = false
	}
}

async function beginOAuth() {
	saving.value = true
	verifyMessage.value = ""
	try {
		const started: any = await call("studio.ai.setup.start_codex_login")
		oauthUrl.value = started?.url ?? ""
		oauthStatus.value = "pending"
		window.open(oauthUrl.value, "_blank", "noopener")
		startPolling(started?.state)
	} catch (e: any) {
		verifyMessage.value = e?.message || "Could not start the sign-in"
	} finally {
		saving.value = false
	}
}

function startPolling(state: string) {
	stopPolling()
	pollTimer = setInterval(async () => {
		try {
			applyOAuth(await call("studio.ai.setup.poll_codex_login", { state }))
		} catch {
			stopPolling()
		}
	}, 1500)
}

async function completeOAuth() {
	saving.value = true
	try {
		applyOAuth(await call("studio.ai.setup.finish_codex_login", { redirect_url: callbackUrl.value.trim() }))
	} catch (e: any) {
		verifyMessage.value = e?.message || "Sign-in failed"
	} finally {
		saving.value = false
	}
}

function applyOAuth(res: any) {
	if (res?.status === "connected") {
		stopPolling()
		oauthStatus.value = "connected"
		toast.success("Signed in with ChatGPT")
		reload()
		emit("changed")
	} else if (["failed", "expired"].includes(res?.status)) {
		stopPolling()
		oauthStatus.value = "idle"
		verifyMessage.value = res?.message || "Sign-in expired — try again."
	}
}

function stopPolling() {
	if (pollTimer) clearInterval(pollTimer)
	pollTimer = null
}

onBeforeUnmount(stopPolling)
</script>
