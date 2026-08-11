<script setup>
import { computed } from 'vue'
import D3SpectrumChart from './D3SpectrumChart.vue'

// Multi-band preview using the full D3SpectrumChart per band, laid out side by
// side at widths proportional to each band's span — so you get the rich chart
// (channel labels, MHz axis, gridlines) for every band without wasting the axis
// on the empty gap between non-contiguous bands. All charts share the fixed
// -110..-20 dBm scale, so the dBm axis is only drawn once (on the first).

const props = defineProps({
  // [{ name, hz_lo, step, power, color? }]
  bands: { type: Array, default: () => [] },
  height: { type: Number, default: 200 },
})

const PALETTE = ['#00d4ff', '#ff9f40', '#4ade80', '#f472b6', '#c084fc', '#facc15']

const layout = computed(() =>
  props.bands
    .filter((b) => b && b.power && b.power.length)
    .map((b, i) => {
      const hzHi = b.hz_lo + (b.step || 1) * b.power.length
      return {
        name: b.name,
        span: hzHi - b.hz_lo,
        band: { name: b.name, start_hz: b.hz_lo, stop_hz: hzHi },
        traces: [{
          id: b.name,
          name: b.name,
          scan: { hz_lo: b.hz_lo, hz_hi: hzHi, step: b.step, power: b.power },
          color: b.color || PALETTE[i % PALETTE.length],
        }],
      }
    })
)
</script>

<template>
  <div class="flex w-full overflow-x-auto band-scroll pb-2">
    <template v-for="(b, i) in layout" :key="b.name">
      <!-- Break marker between non-contiguous bands -->
      <div
        v-if="i > 0"
        class="flex items-center justify-center text-gray-600 text-sm shrink-0 px-1 select-none"
        :style="{ height: height + 'px' }"
      >⁄⁄</div>
      <div
        class="min-w-0 snap-start"
        :style="{ flexGrow: b.span, flexBasis: 0, minWidth: (i === 0 ? 220 : 150) + 'px' }"
      >
        <D3SpectrumChart :traces="b.traces" :band="b.band" :hide-y-axis="i > 0" :height="height" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.band-scroll {
  scroll-snap-type: x proximity;
  scrollbar-width: thin;
  scrollbar-color: #4b5563 transparent;
}
.band-scroll::-webkit-scrollbar {
  height: 8px;
}
.band-scroll::-webkit-scrollbar-track {
  background: transparent;
}
.band-scroll::-webkit-scrollbar-thumb {
  background: #4b5563;
  border-radius: 9999px;
}
.band-scroll::-webkit-scrollbar-thumb:hover {
  background: #6b7280;
}
</style>
