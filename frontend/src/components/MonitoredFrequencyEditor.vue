<script setup>
import { ref, computed, onMounted } from 'vue'
import { useScannersStore } from '../stores/scanners'

// Per-scanner monitored-frequency editor, shown in a band's waterfall. Lists the
// frequencies that fall in this band and lets an rw/staff user add/edit/remove
// them. The server enforces permissions and applies the scanner scope; this just
// drives the CRUD store methods. Read-only display of pins stays in the charts.
const props = defineProps({
  scannerId: { type: String, required: true },
  band: { type: Object, required: true },          // { name, start_hz, stop_hz }
  frequencies: { type: Array, default: () => [] },  // all of the scanner's monitored freqs
})

const store = useScannersStore()

// Combobox options: predefined + any category already in the DB (e.g. a custom
// "Public Safety") — sourced from the API, not a hard-coded list.
const categoryOptions = computed(() => store.getMonitoredCategories())
const listId = `mf-cat-${(props.band.name || 'x').replace(/\W/g, '')}`
onMounted(() => store.fetchMonitoredCategories())

const hzToMHz = (hz) => Math.round((Number(hz) || 0) / 1e6 * 1000) / 1000
const mhzToHz = (mhz) => Math.round((Number(mhz) || 0) * 1e6)

// Only the freqs inside this band, sorted.
const bandFreqs = computed(() =>
  props.frequencies
    .filter((f) => f.frequency_hz >= props.band.start_hz && f.frequency_hz <= props.band.stop_hz)
    .sort((a, b) => a.frequency_hz - b.frequency_hz),
)

const busy = ref(false)
const error = ref('')

// ── Inline edit of an existing row ──
const editingId = ref(null)
const editDraft = ref({ name: '', mhz: null, category: 'Wireless Mics' })

function startEdit(f) {
  editingId.value = f.id
  editDraft.value = { name: f.name, mhz: hzToMHz(f.frequency_hz), category: f.category }
  error.value = ''
}
function cancelEdit() {
  editingId.value = null
}
async function saveEdit(f) {
  if (!validDraft(editDraft.value)) return
  await run(() =>
    store.updateMonitoredFrequency(props.scannerId, f.id, {
      name: editDraft.value.name.trim(),
      frequency_hz: mhzToHz(editDraft.value.mhz),
      category: editDraft.value.category,
    }),
  )
  editingId.value = null
}
async function remove(f) {
  await run(() => store.deleteMonitoredFrequency(props.scannerId, f.id))
}

// ── Add a new row ──
const adding = ref(false)
const newFreq = ref({ name: '', mhz: null, category: 'Wireless Mics' })
function startAdd() {
  adding.value = true
  newFreq.value = { name: '', mhz: hzToMHz((props.band.start_hz + props.band.stop_hz) / 2), category: 'Wireless Mics' }
  error.value = ''
}
async function saveAdd() {
  if (!validDraft(newFreq.value)) return
  await run(() =>
    store.createMonitoredFrequency(props.scannerId, {
      name: newFreq.value.name.trim(),
      frequency_hz: mhzToHz(newFreq.value.mhz),
      category: newFreq.value.category,
    }),
  )
  adding.value = false
}

function validDraft(d) {
  if (!d.name || !d.name.trim()) { error.value = 'Name required'; return false }
  const mhz = Number(d.mhz)
  if (!Number.isFinite(mhz) || mhz <= 0) { error.value = 'Valid frequency (MHz) required'; return false }
  error.value = ''
  return true
}

async function run(fn) {
  busy.value = true
  error.value = ''
  try {
    await fn()
  } catch (e) {
    error.value = `Failed: ${e.message}`
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="mt-2 rounded bg-gray-900/60 p-2 text-sm">
    <div class="flex items-center justify-between mb-1">
      <h5 class="text-xs font-semibold text-gray-400">Monitored Frequencies — {{ band.name }}</h5>
      <button v-if="!adding" @click="startAdd" class="text-xs text-cyan-400 hover:text-cyan-300">+ Add</button>
    </div>

    <p v-if="error" class="text-red-400 text-xs mb-1">{{ error }}</p>

    <div v-if="bandFreqs.length === 0 && !adding" class="text-xs text-gray-500 py-1">
      No monitored frequencies in this band yet.
    </div>

    <div class="space-y-1">
      <div v-for="f in bandFreqs" :key="f.id" class="flex items-center gap-2">
        <template v-if="editingId === f.id">
          <input v-model="editDraft.name" placeholder="name"
                 class="mf-in w-24" />
          <input type="number" step="0.001" v-model.number="editDraft.mhz"
                 class="mf-in no-spin w-24 text-right" />
          <span class="text-gray-500 text-xs">MHz</span>
          <input v-model="editDraft.category" :list="listId" placeholder="category"
                 class="mf-in text-xs w-28" />
          <button @click="saveEdit(f)" :disabled="busy"
                  class="text-xs text-cyan-400 hover:text-cyan-300">Save</button>
          <button @click="cancelEdit" class="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
        </template>
        <template v-else>
          <span class="inline-block w-2 h-2 rounded-full shrink-0" :style="{ backgroundColor: f.color }"></span>
          <span class="font-medium w-24 truncate" :title="f.name">{{ f.name }}</span>
          <span class="text-gray-300 w-24 text-right">{{ hzToMHz(f.frequency_hz).toFixed(3) }}</span>
          <span class="text-gray-500 text-xs">MHz</span>
          <span class="text-gray-500 text-xs flex-1 truncate">{{ f.category }}</span>
          <button @click="startEdit(f)" class="text-xs text-gray-400 hover:text-gray-200">Edit</button>
          <button @click="remove(f)" :disabled="busy"
                  class="text-gray-500 hover:text-red-400 px-1" title="Remove">✕</button>
        </template>
      </div>
    </div>

    <div v-if="adding" class="flex items-center gap-2 mt-1 border-t border-gray-700 pt-1">
      <input v-model="newFreq.name" placeholder="name" class="mf-in w-24" />
      <input type="number" step="0.001" v-model.number="newFreq.mhz"
             placeholder="MHz" class="mf-in no-spin w-24 text-right" />
      <span class="text-gray-500 text-xs">MHz</span>
      <input v-model="newFreq.category" :list="listId" placeholder="category"
             class="mf-in text-xs w-28" />
      <button @click="saveAdd" :disabled="busy"
              class="text-xs font-semibold text-cyan-400 hover:text-cyan-300">Add</button>
      <button @click="adding = false" class="text-xs text-gray-500 hover:text-gray-300">Cancel</button>
    </div>

    <datalist :id="listId">
      <option v-for="c in categoryOptions" :key="c" :value="c" />
    </datalist>
  </div>
</template>

<style scoped>
.mf-in {
  background: #111827;
  color: #fff;
  border: 1px solid #4b5563;
  border-radius: 0.25rem;
  padding: 0.15rem 0.4rem;
  font-size: 0.75rem;
}
.mf-in:focus {
  outline: none;
  border-color: #22d3ee;
}
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
