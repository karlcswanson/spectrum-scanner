<script setup>
import { ref, computed, watch } from 'vue'
import { useScannersStore } from '../stores/scanners'
import MultiBandPreview from './MultiBandPreview.vue'
import { buildBandTrace, buildCSV, exportFilename, downloadText } from '../lib/spectrumExport'

const props = defineProps({
  scannerId: { type: String, required: true },
  scannerName: { type: String, default: '' },
  open: { type: Boolean, default: false },
  // The band the export was opened from (pre-selected).
  initialBand: { type: String, default: null },
  // The currently-displayed scan for the initial band (live or scrubbed).
  activeScan: { type: Object, default: null },
  // Whether the band view is on live data (true) or scrubbed to a past time.
  isLive: { type: Boolean, default: true },
  // The selected time range from the band view ({ hours } or { start, end }).
  // Used for Peak/Average — we do NOT invent a separate range picker.
  timeRange: { type: Object, default: null },
})
const emit = defineEmits(['close'])

const store = useScannersStore()

const trace = ref('live') // 'live' | 'peak' | 'average'
const busy = ref(false)
const previewLoading = ref(false)
const error = ref('')

const enabledBands = computed(() =>
  (store.scanners[props.scannerId]?.bands || [])
    .filter((b) => b.enabled)
    .sort((a, b) => (Number(a.start_hz) || 0) - (Number(b.start_hz) || 0))
)

const selected = ref(new Set())

const selectedBandList = computed(() =>
  enabledBands.value.filter((b) => selected.value.has(b.name))
)

const needsRange = computed(() => trace.value !== 'live')

// When the band view is scrubbed to a past time, the "current" trace exports the
// scan AT that time, not live. This is the timestamp to match for other bands.
const selectedTime = computed(() => (!props.isLive ? props.activeScan?.timestamp : null))

// Peak/Average are kept visible but disabled until their reduction is qualified.
// Flip this to true to re-enable them.
const PEAK_AVG_ENABLED = false

// First trace is "Live" on live data, "Selected" when scrubbed to a past time.
const traceOptions = computed(() => [
  { key: 'live', label: props.isLive ? 'Live' : 'Selected', disabled: false },
  { key: 'peak', label: 'Peak', disabled: !PEAK_AVG_ENABLED },
  { key: 'average', label: 'Average', disabled: !PEAK_AVG_ENABLED },
])

// Human label for the range being used (read-only — it comes from the band view).
const rangeLabel = computed(() => {
  const r = props.timeRange
  if (!r) return 'selected range'
  if (r.start && r.end) {
    const fmt = (d) => new Date(d).toLocaleString()
    return `${fmt(r.start)} → ${fmt(r.end)}`
  }
  if (r.hours != null) {
    const h = Number(r.hours)
    return h < 1 ? `last ${Math.round(h * 60)} min` : `last ${h} h`
  }
  return 'selected range'
})

function toggleBand(name) {
  const next = new Set(selected.value)
  if (next.has(name)) {
    if (next.size > 1) next.delete(name)
  } else {
    next.add(name)
  }
  selected.value = next
}

// --- data assembly -------------------------------------------------------

function normLive(scan) {
  return scan && scan.power ? { hz_lo: scan.hz_lo, step: scan.step, power: scan.power } : null
}

async function scansForBand(bandName) {
  if (trace.value === 'live') {
    // The band we opened from: exactly what's on screen (live OR scrubbed).
    if (bandName === props.initialBand && props.activeScan) {
      const n = normLive(props.activeScan)
      return n ? [n] : []
    }
    // Other bands: when scrubbed, match the selected time; else latest live.
    if (selectedTime.value) {
      const s = await store.fetchScanAtTime(props.scannerId, selectedTime.value, bandName)
      return s ? [{ hz_lo: s.hz_lo, step: s.step_hz, power: s.power }] : []
    }
    const live = normLive(store.bandScans[props.scannerId]?.[bandName])
    return live ? [live] : []
  }
  // Peak / Average: full-resolution history over the band view's selected range.
  const rows = await store.fetchHistory(props.scannerId, bandName, {
    ...(props.timeRange || { hours: 1 }),
    limit: 5000,
    decimated: false, // exports are always full-resolution
  })
  return (rows || [])
    .slice()
    .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
    .map((s) => ({ hz_lo: s.hz_lo, step: s.step_hz, power: s.power }))
}

// The prepared traces — the single source of truth for BOTH the preview and the
// exported file, so what you see is exactly what you get.
const prepared = ref([]) // [{ name, hz_lo, step, power }]
let recomputeToken = 0

async function recompute() {
  if (!props.open) return
  const token = ++recomputeToken
  previewLoading.value = true
  error.value = ''
  try {
    const out = []
    for (const band of selectedBandList.value) {
      const scans = await scansForBand(band.name)
      const t = buildBandTrace(scans, trace.value)
      if (t) out.push({ name: band.name, ...t })
    }
    if (token !== recomputeToken) return // superseded
    prepared.value = out
  } catch (e) {
    if (token === recomputeToken) error.value = `Preview failed: ${e.message || e}`
  } finally {
    if (token === recomputeToken) previewLoading.value = false
  }
}

// Reset selection + recompute whenever opened; recompute on any option change.
watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return
    error.value = ''
    const first = props.initialBand || enabledBands.value[0]?.name
    selected.value = new Set(first ? [first] : [])
    recompute()
  },
  { immediate: true }
)
watch([trace, selected, () => props.timeRange, () => props.activeScan, () => props.isLive], recompute, { deep: true })

// --- preview + export ----------------------------------------------------

const filenamePreview = computed(() => {
  const bands = selectedBandList.value.map((b) => ({
    name: b.name,
    hz_lo: Number(b.start_hz),
    hz_hi: Number(b.stop_hz),
  }))
  return bands.length ? exportFilename(bands, trace.value) : ''
})

const pointCount = computed(() => prepared.value.reduce((n, t) => n + t.power.length, 0))

function doExport() {
  if (busy.value || !prepared.value.length) return
  busy.value = true
  try {
    const bands = selectedBandList.value.map((b) => ({
      name: b.name,
      hz_lo: Number(b.start_hz),
      hz_hi: Number(b.stop_hz),
    }))
    downloadText(exportFilename(bands, trace.value), buildCSV(prepared.value))
    emit('close')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    @click.self="emit('close')"
  >
    <div class="w-full max-w-4xl bg-gray-800 rounded-lg shadow-xl border border-gray-700 max-h-[90vh] overflow-y-auto">
      <div class="flex items-center justify-between px-5 py-3 border-b border-gray-700">
        <h3 class="text-base font-semibold text-white">Export scans</h3>
        <button
          class="p-1 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-700"
          aria-label="Close"
          @click="emit('close')"
        >
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div class="px-5 py-4 space-y-5">
        <!-- Preview — exactly what will be exported -->
        <div>
          <div class="flex items-center justify-between mb-2">
            <h4 class="text-sm font-medium text-gray-300">Preview</h4>
            <span v-if="previewLoading" class="text-xs text-gray-500">loading…</span>
            <span v-else-if="pointCount" class="text-xs text-gray-500">{{ pointCount.toLocaleString() }} points</span>
          </div>
          <div class="bg-gray-900 rounded-lg p-2 min-h-[180px] flex items-center justify-center">
            <MultiBandPreview
              v-if="prepared.length"
              :bands="prepared"
              :height="200"
            />
            <p v-else class="text-sm text-gray-500">
              {{ trace === 'live' ? 'No live scan for the selected band(s).' : 'No scans in the selected range.' }}
            </p>
          </div>
        </div>

        <!-- Trace -->
        <div>
          <h4 class="text-sm font-medium text-gray-300 mb-2">Trace</h4>
          <div class="inline-flex rounded-md overflow-hidden border border-gray-600">
            <button
              v-for="opt in traceOptions"
              :key="opt.key"
              :disabled="opt.disabled"
              :title="opt.disabled ? 'Coming soon' : ''"
              class="px-4 py-1.5 text-sm transition-colors"
              :class="[
                trace === opt.key ? 'bg-cyan-500 text-black font-medium' : 'bg-gray-800 text-gray-300 hover:bg-gray-700',
                opt.disabled ? 'opacity-40 cursor-not-allowed hover:bg-gray-800' : '',
              ]"
              @click="opt.disabled || (trace = opt.key)"
            >
              {{ opt.label }}
            </button>
          </div>
          <p v-if="needsRange" class="mt-1.5 text-xs text-gray-500">
            {{ trace === 'peak' ? 'Per-bin max' : 'Per-bin average' }} over {{ rangeLabel }}.
          </p>
          <p v-else class="mt-1.5 text-xs text-gray-500">
            {{ isLive ? 'Latest sweep for each band.' : 'Scan at the selected time.' }}
            <span v-if="!PEAK_AVG_ENABLED" class="text-gray-600"> · Peak/Average coming soon.</span>
          </p>
        </div>

        <!-- Bands -->
        <div>
          <h4 class="text-sm font-medium text-gray-300 mb-2">Bands</h4>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="b in enabledBands"
              :key="b.name"
              class="px-3 py-1.5 rounded text-sm border transition-colors"
              :class="selected.has(b.name)
                ? 'bg-cyan-900/50 border-cyan-500 text-cyan-300'
                : 'bg-gray-700 border-transparent text-gray-300 hover:bg-gray-600'"
              @click="toggleBand(b.name)"
            >
              {{ b.name }}
            </button>
          </div>
        </div>

        <!-- Filename -->
        <div v-if="filenamePreview" class="text-xs text-gray-500 font-mono break-all">
          {{ filenamePreview }}
        </div>

        <div v-if="error" class="text-sm text-red-400 bg-red-900/30 border border-red-500/50 rounded px-3 py-2">
          {{ error }}
        </div>
      </div>

      <div class="flex justify-end gap-2 px-5 py-3 border-t border-gray-700">
        <button class="px-4 py-1.5 text-sm rounded text-gray-300 hover:bg-gray-700" @click="emit('close')">
          Cancel
        </button>
        <button
          class="px-4 py-1.5 text-sm rounded bg-cyan-500 hover:bg-cyan-600 text-black font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="busy || previewLoading || !prepared.length"
          @click="doExport"
        >
          {{ busy ? 'Exporting…' : 'Export CSV' }}
        </button>
      </div>
    </div>
  </div>
</template>
