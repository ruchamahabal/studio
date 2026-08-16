<template>
	<Dialog
		v-model="show"
		:options="{ title: selected ? presetTitle : 'AI Providers', size: 'lg' }"
		@after-leave="reset"
	>
		<template #body-content>
			<!-- provider list -->
			<div v-if="!selected" class="flex flex-col">
				<p class="mb-2 text-p-sm text-ink-gray-6">
					Connect a provider to power the AI assistant. Keys stay on your site.
				</p>
				<button
					v-for="p in presets"
					:key="p.id"
					class="flex w-full items-center gap-3 rounded-md px-2.5 py-2.5 text-left hover:bg-surface-gray-2"
					@click="select(p)"
				>
					<span class="min-w-0 flex-1">
						<span class="block truncate text-p-sm font-medium text-ink-gray-8">
							{{ p.custom ? "Add custom endpoint" : p.name }}
						</span>
						<span class="mt-0.5 block truncate text-p-xs text-ink-gray-5">{{ p.tagline }}</span>
					</span>
					<span v-if="p.configured" class="flex items-center gap-1 text-p-xs font-medium text-ink-green-6">
						<span class="h-1.5 w-1.5 rounded-full bg-surface-green-6" />
						Connected
					</span>
					<FeatherIcon v-else name="chevron-right" class="h-4 w-4 text-ink-gray-4" />
				</button>
			</div>

			<!-- provider detail -->
			<div v-else class="flex flex-col gap-4">
				<Button variant="ghost" size="sm" class="w-fit" @click="deselect">
					<template #prefix>
						<FeatherIcon name="arrow-left" class="h-3.5 w-3.5" />
					</template>
					All providers
				</Button>

				<p class="text-p-sm text-ink-gray-6">{{ selected.blurb }}</p>

				<!-- ChatGPT sign-in (OAuth) -->
				<div v-if="selected.oauth" class="flex flex-col gap-3">
					<div
						v-if="oauthStatus === 'connected' || (selected.configured && oauthStatus === 'idle')"
						class="flex items-center gap-2 rounded-md border border-outline-gray-1 bg-surface-gray-1 px-3 py-2.5 text-p-sm text-ink-gray-7"
					>
						<FeatherIcon name="check-circle" class="h-4 w-4 text-ink-green-3" />
						Signed in with ChatGPT
					</div>
					<Button
						v-else-if="oauthStatus !== 'pending'"
						variant="solid"
						label="Sign in with ChatGPT"
						class="w-fit"
						:loading="saving"
						@click="beginOAuth"
					/>
					<div
						v-else
						class="rounded-md border border-outline-gray-1 bg-surface-gray-1 px-3 py-2.5 text-p-sm text-ink-gray-7"
					>
						Waiting for sign-in…
					</div>
					<!-- popup blockers eat window.open — a plain link is the reliable path -->
					<a
						v-if="oauthUrl && oauthStatus === 'pending'"
						:href="oauthUrl"
						target="_blank"
						rel="noopener noreferrer"
						class="flex w-fit items-center gap-1.5 text-p-sm text-ink-gray-6 underline hover:text-ink-gray-9"
					>
						<FeatherIcon name="external-link" class="h-3.5 w-3.5" />
						Open the sign-in page
					</a>
					<button
						v-if="oauthStatus === 'pending' && !showManual"
						class="w-fit text-p-sm text-ink-gray-5 hover:text-ink-gray-8"
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
							class="flex-1"
							placeholder="http://localhost:1455/auth/callback?..."
						/>
						<Button
							variant="subtle"
							label="Complete"
							:disabled="!callbackUrl.trim() || saving"
							@click="completeOAuth"
						/>
					</form>
				</div>

				<!-- API key entry -->
				<div v-else class="flex flex-col gap-4">
					<ol v-if="selected.key_steps?.length && !selected.custom" class="flex flex-col gap-1.5 pl-1">
						<li
							v-for="(step, i) in selected.key_steps as string[]"
							:key="step"
							class="flex gap-2 text-p-sm text-ink-gray-7"
						>
							<span class="text-ink-gray-4">{{ i + 1 }}</span>
							<span>{{ step }}</span>
						</li>
					</ol>
					<Button
						v-if="selected.key_url"
						variant="subtle"
						size="sm"
						label="Open key page"
						icon-right="lucide-external-link"
						:href="selected.key_url"
						target="_blank"
						rel="noopener noreferrer"
						class="w-fit"
					/>
					<FormControl
						v-if="selected.needs_name"
						v-model="providerName"
						label="Name"
						type="text"
						placeholder="Local Ollama"
					/>
					<FormControl
						v-if="selected.needs_api_base"
						v-model="apiBase"
						label="Base URL"
						type="text"
						placeholder="http://localhost:11434/v1"
					/>
					<div class="flex flex-col gap-1.5">
						<FormControl
							v-model="apiKey"
							:label="selected.custom ? 'API key (optional)' : 'API key'"
							type="password"
							autocomplete="off"
							:placeholder="selected.has_key ? 'Stored, leave blank to keep it' : keyPlaceholder"
						/>
					</div>
				</div>

				<!-- model selection -->
				<div v-if="selected.models?.length" class="flex flex-col gap-1">
					<span class="text-p-sm font-medium text-ink-gray-8">Models to enable</span>
					<!-- the label wraps the checkbox, so clicking anywhere on the row toggles it
						 through the native label-input association — no duplicate click handler -->
					<label
						v-for="m in selected.models"
						:key="m.model_id"
						class="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-surface-gray-2"
					>
						<Checkbox
							:model-value="chosenModels.includes(m.model_id)"
							@update:model-value="toggleModel(m.model_id)"
						/>
						<span class="min-w-0 flex-1 truncate text-p-sm text-ink-gray-8">{{ m.label }}</span>
					</label>
				</div>
				<div v-if="selected.custom" class="flex flex-col gap-1.5">
					<FormControl
						v-model="customModelIds"
						label="Model ids"
						type="textarea"
						placeholder="llama3.2&#10;qwen2.5"
					/>
					<p class="text-p-xs text-ink-gray-5">
						One per line — or connect first and use "Import models" to ask the endpoint.
					</p>
				</div>

				<!-- any other model this provider serves, by its exact id -->
				<div v-if="selected.configured && !selected.custom" class="flex flex-col gap-1.5">
					<span class="text-p-sm font-medium text-ink-gray-8">Add another model</span>
					<div class="flex gap-2">
						<FormControl
							v-model="newModelId"
							type="text"
							class="flex-1"
							placeholder="anthropic/claude-opus-4.6"
							@keydown.enter.prevent="addModelById"
						/>
						<Button
							variant="subtle"
							label="Add"
							:loading="addingModel"
							:disabled="!newModelId.trim()"
							@click="addModelById"
						/>
					</div>
					<p class="text-p-xs text-ink-gray-5">
						The provider's exact model id — enabled immediately, context window and vision detected
						automatically.
					</p>
				</div>

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
						variant="subtle"
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
import { Dialog, Button, Checkbox, FormControl, ErrorMessage, FeatherIcon, call, toast } from "frappe-ui"

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
const newModelId = ref("")
const addingModel = ref(false)

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
	newModelId.value = ""
	// A connected provider shows its real state; a fresh one starts from the
	// shortlist's recommendations.
	const models = p.models ?? []
	chosenModels.value = (
		p.configured ? models.filter((m: any) => m.enabled) : models.filter((m: any) => m.recommended)
	).map((m: any) => m.model_id)
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

async function addModelById() {
	const modelId = newModelId.value.trim()
	if (!modelId || !selected.value) return
	addingModel.value = true
	try {
		const res: any = await call("studio.ai.setup.add_provider_model", {
			provider: selected.value.name,
			model_id: modelId,
		})
		if (res?.known) toast.success(`${res.name} added`)
		else toast.warning(`${res.name} added — no catalog knows this id, double-check it`)
		newModelId.value = ""
		await reload()
		emit("changed")
	} catch (e: any) {
		verifyMessage.value = e?.message || "Could not add the model"
	} finally {
		addingModel.value = false
	}
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
