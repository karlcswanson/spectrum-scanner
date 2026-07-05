<script setup>
import { ref, computed, watch } from 'vue'
import { useScannersStore } from '../stores/scanners'
import { DEFAULT_BANDS } from '../constants'

// Per-scanner band editor. Edits are batched into a local draft and sent as the
// full desired band list over MQTT (declarative — the scanner reconciles to it;
// see docs/remote-band-editing.md). Rename is disallowed in v1 (band name is the
// history key), so existing names are read-only; only new bands name themselves.
const props = defineProps({
  scannerId: { type: String, required: true },
  // Current bands from the scanner config: [{ name, start_hz, stop_hz, enabled }]
  bands: { type: Array, default: () => [] },
  // Scanner online state — Save is disabled when offline, since the scanner must
  // be connected to receive, apply, and persist the change.
  online: { type: Boolean, default: true },
})

// Only block on a confirmed-offline signal (lenient when status is unknown).
const offline = computed(() => props.online === false)

const store = useScannersStore()

const draft = ref([])
const justSaved = ref(false)
// True once the user edits the draft — guards against an incoming config echo
// clobbering unsaved edits, while still letting the draft load when bands
// arrive after mount (or resync after a save).
const touched = ref(false)

const hzToMHz = (hz) => Math.round((Number(hz) || 0) / 1e6 * 1000) / 1000
const mhzToHz = (mhz) => Math.round((Number(mhz) || 0) * 1e6)

function toDraft(bands) {
  return bands.map((b) => ({
    name: b.name,
    startMHz: hzToMHz(b.start_hz),
    stopMHz: hzToMHz(b.stop_hz),
    enabled: !!b.enabled,
    isNew: false,
  }))
}
function loadDraft() {
  draft.value = toDraft(props.bands)
}
loadDraft()

// Canonical {name, start_hz, stop_hz, enabled} sorted by name, for dirty compare.
function normalize(list) {
  return JSON.stringify(
    list
      .map((b) => ({
        name: (b.name || '').trim(),
        start_hz: b.isNew !== undefined ? mhzToHz(b.startMHz) : Number(b.start_hz),
        stop_hz: b.isNew !== undefined ? mhzToHz(b.stopMHz) : Number(b.stop_hz),
        enabled: !!b.enabled,
      }))
      .sort((a, b) => a.name.localeCompare(b.name)),
  )
}

const dirty = computed(() => normalize(draft.value) !== normalize(props.bands))

// Keep the draft in sync with the scanner's real config unless the user has
// unsaved edits (touched), and always right after a save (the scanner echoes its
// applied config back — that's the source of truth). This also loads the draft
// when bands arrive over MQTT after mount.
watch(
  () => props.bands,
  () => {
    if (justSaved.value || !touched.value) {
      loadDraft()
      touched.value = false
      justSaved.value = false
    }
  },
  { deep: true },
)

// ── Validation (mirrors the scanner rules; the scanner is the final authority
//    on hardware range) ──
const MAX_MHZ = 6000 // Pluto tops out ~6 GHz; a soft sanity bound.

function rowError(row) {
  if (!row.name || !row.name.trim()) return 'Name required'
  const s = Number(row.startMHz)
  const e = Number(row.stopMHz)
  if (!Number.isFinite(s) || !Number.isFinite(e)) return 'Numbers required'
  // Whole MHz only — config.yaml persists band edges as integer MHz.
  if (!Number.isInteger(s) || !Number.isInteger(e)) return 'Whole MHz only'
  if (s <= 0 || e <= 0) return 'Must be > 0'
  if (s >= e) return 'Start must be < stop'
  if (e > MAX_MHZ) return `Above ${MAX_MHZ} MHz`
  return null
}

const dupeNames = computed(() => {
  const seen = new Set()
  const dupes = new Set()
  for (const b of draft.value) {
    const n = (b.name || '').trim().toLowerCase()
    if (!n) continue
    if (seen.has(n)) dupes.add(n)
    seen.add(n)
  }
  return dupes
})

const errors = computed(() =>
  draft.value.map((row) => {
    const e = rowError(row)
    if (e) return e
    if (dupeNames.value.has((row.name || '').trim().toLowerCase())) return 'Duplicate name'
    return null
  }),
)

const valid = computed(() => errors.value.every((e) => e === null))

// ── Actions ──
function addBand() {
  draft.value.push({ name: '', startMHz: null, stopMHz: null, enabled: true, isNew: true })
  touched.value = true
}

function removeBand(idx) {
  draft.value.splice(idx, 1)
  touched.value = true
}

function discard() {
  loadDraft()
  touched.value = false
}

// Load the canonical default band set into the draft — the user reviews it and
// Saves (or Discards) like any other edit; it's not pushed immediately.
function resetToDefaults() {
  draft.value = toDraft(DEFAULT_BANDS)
  touched.value = true
}

function save() {
  if (!valid.value || !dirty.value || offline.value) return
  const bands = draft.value.map((b) => ({
    name: b.name.trim(),
    start_hz: mhzToHz(b.startMHz),
    stop_hz: mhzToHz(b.stopMHz),
    enabled: !!b.enabled,
  }))
  const ok = store.sendBandsCommand(props.scannerId, bands)
  if (ok) justSaved.value = true
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-3 gap-2">
      <div class="flex items-center gap-2">
        <h4 class="text-sm font-semibold text-gray-400">Bands</h4>
        <span
          v-if="offline"
          class="px-2 py-0.5 rounded-full text-[11px] bg-amber-900/60 text-amber-300"
        >
          scanner offline
        </span>
      </div>
      <div v-if="dirty" class="flex items-center gap-2">
        <button
          @click="discard"
          class="px-3 py-1 rounded text-sm bg-gray-700 hover:bg-gray-600 text-gray-200"
        >
          Discard
        </button>
        <button
          @click="save"
          :disabled="!valid || offline"
          class="px-3 py-1 rounded text-sm font-semibold transition-colors"
          :class="valid && !offline
            ? 'bg-cyan-600 hover:bg-cyan-500 text-white'
            : 'bg-gray-700 text-gray-500 cursor-not-allowed'"
        >
          Save changes
        </button>
      </div>
    </div>

    <div class="space-y-2">
      <div
        v-for="(row, idx) in draft"
        :key="idx"
        class="flex flex-wrap items-center gap-2 rounded px-2 py-1.5"
        :class="row.enabled ? 'bg-cyan-900/30' : 'bg-gray-700/40'"
      >
        <input
          type="checkbox"
          v-model="row.enabled"
          @change="touched = true"
          class="w-4 h-4 accent-cyan-400 shrink-0"
          title="Enable / disable this band"
        />
        <!-- Name: editable only for new bands (rename disallowed in v1) -->
        <input
          v-if="row.isNew"
          v-model="row.name"
          @input="touched = true"
          placeholder="Band name"
          class="bg-gray-900 text-white text-sm rounded border border-gray-600 focus:border-cyan-400 focus:outline-none px-2 py-1 w-32"
        />
        <span v-else class="font-medium w-32 truncate" :title="row.name">{{ row.name }}</span>

        <!-- Whole-MHz numeric fields. Native spinners removed (inconsistent
             across browsers); type the value into a plain dark-styled input. -->
        <input
          type="number"
          inputmode="numeric"
          v-model.number="row.startMHz"
          @input="touched = true"
          min="1"
          placeholder="start"
          aria-label="Start MHz"
          class="no-spin bg-gray-900 text-white text-sm rounded border border-gray-600 focus:border-cyan-400 focus:outline-none px-2 py-1 w-20 text-right"
        />
        <span class="text-gray-500">–</span>
        <input
          type="number"
          inputmode="numeric"
          v-model.number="row.stopMHz"
          @input="touched = true"
          min="1"
          placeholder="stop"
          aria-label="Stop MHz"
          class="no-spin bg-gray-900 text-white text-sm rounded border border-gray-600 focus:border-cyan-400 focus:outline-none px-2 py-1 w-20 text-right"
        />
        <span class="text-gray-400 text-sm">MHz</span>

        <span v-if="errors[idx]" class="text-red-400 text-xs">{{ errors[idx] }}</span>

        <button
          @click="removeBand(idx)"
          class="ml-auto text-gray-500 hover:text-red-400 px-2"
          title="Remove band"
        >
          ✕
        </button>
      </div>
    </div>

    <div class="mt-3 flex items-center justify-between gap-2">
      <div class="flex items-center gap-4">
        <button @click="addBand" class="text-sm text-cyan-400 hover:text-cyan-300">
          + Add band
        </button>
        <button @click="resetToDefaults" class="text-sm text-gray-400 hover:text-gray-300">
          Reset to defaults
        </button>
      </div>
      <p class="text-xs text-gray-500">
        {{ offline
          ? 'Scanner must be online to apply band changes.'
          : 'Frequencies in whole MHz. Changes are sent to the scanner, which applies and persists them.' }}
      </p>
    </div>
  </div>
</template>

<style scoped>
/* Remove the native number-input spinners — Chrome shows them only on hover,
   Safari/Firefox differ. A plain typeable field is consistent across browsers. */
.no-spin::-webkit-outer-spin-button,
.no-spin::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
.no-spin {
  -moz-appearance: textfield;
  appearance: textfield;
}
</style>
