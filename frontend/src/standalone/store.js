import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useEventBus } from '@vueuse/core'

// Event bus for scan redraw signals (same key = same instance across app)
export const scanBus = useEventBus('scan-redraw')

/**
 * Standalone scanner store - connects directly to Go scanner API
 * No MQTT, no auth - just local WebSocket and REST API
 */
export const useStandaloneStore = defineStore('standalone', () => {
  // Scanner state
  const config = ref(null)
  const status = ref(null)
  const connected = ref(false)
  const lastError = ref(null)

  // Scan data stored in plain object (NOT reactive) for performance
  const scanDataRaw = {}

  // Lightweight reactive counter for template updates (scan info text)
  const scanUpdateCount = ref(0)

  // WebSocket connection
  let ws = null
  let reconnectTimeout = null

  // Computed
  const scanning = computed(() => status.value?.scanning || false)
  const currentBand = computed(() => status.value?.current_band || null)
  const bands = computed(() => {
    if (!config.value?.bands) return []
    return config.value.bands
      .slice()
      .sort((a, b) => (a.start_hz || 0) - (b.start_hz || 0))
  })
  const enabledBands = computed(() => bands.value.filter(b => b.enabled))
  const settings = computed(() => ({
    rx_gain: config.value?.rx_gain || 40,
    rx_gain_mode: config.value?.rx_gain_mode || 'manual',
  }))

  // Connect WebSocket for live scan data
  function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/stream`

    console.log('Connecting to WebSocket:', wsUrl)
    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      console.log('WebSocket connected')
      connected.value = true
      lastError.value = null
      // Fetch initial config
      fetchConfig()
      fetchStatus()
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        // Handle typed messages: { type: "scan" | "status", data: {...} }
        if (msg.type === 'scan') {
          handleScanData(msg.data)
        } else if (msg.type === 'status') {
          handleStatusUpdate(msg.data)
        } else {
          // Legacy format (raw scan data)
          handleScanData(msg)
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err)
      }
    }

    ws.onclose = () => {
      console.log('WebSocket disconnected')
      connected.value = false
      // Reconnect after delay
      reconnectTimeout = setTimeout(connect, 2000)
    }

    ws.onerror = (err) => {
      console.error('WebSocket error:', err)
      lastError.value = { message: 'WebSocket connection error', timestamp: Date.now() }
    }
  }

  function disconnect() {
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout)
      reconnectTimeout = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
    connected.value = false
  }

  function handleScanData(data) {
    // Go scanner sends: { band, hz_lo, hz_hi, step, power: [...], timestamp }
    if (data.band && data.power) {
      // Store in plain object (no Vue overhead)
      scanDataRaw[data.band] = {
        hz_lo: data.hz_lo,
        hz_hi: data.hz_hi,
        step: data.step,
        power: data.power,
        timestamp: data.timestamp,
      }

      // Signal chart to redraw
      scanBus.emit(data.band)

      // Bump counter for template updates (scan info text)
      scanUpdateCount.value++
    }
  }

  // Get scan data for a band (called by chart component)
  function getScanData(bandName) {
    return scanDataRaw[bandName] || null
  }

  function handleStatusUpdate(data) {
    // Update status from WebSocket push
    if (!status.value) {
      status.value = {}
    }
    status.value = {
      ...status.value,
      scanning: data.scanning,
      current_band: data.current_band,
    }
  }

  // REST API calls
  async function fetchConfig() {
    try {
      const response = await fetch('/api/config')
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      config.value = await response.json()
    } catch (err) {
      console.error('Failed to fetch config:', err)
      lastError.value = { message: `Config: ${err.message}`, timestamp: Date.now() }
    }
  }

  async function fetchStatus() {
    try {
      const response = await fetch('/api/status')
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      status.value = await response.json()
    } catch (err) {
      console.error('Failed to fetch status:', err)
    }
  }

  async function startScanning() {
    try {
      const response = await fetch('/api/scan/start', { method: 'POST' })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await fetchStatus()
    } catch (err) {
      console.error('Failed to start scanning:', err)
      lastError.value = { message: `Start: ${err.message}`, timestamp: Date.now() }
    }
  }

  async function stopScanning() {
    try {
      const response = await fetch('/api/scan/stop', { method: 'POST' })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await fetchStatus()
    } catch (err) {
      console.error('Failed to stop scanning:', err)
      lastError.value = { message: `Stop: ${err.message}`, timestamp: Date.now() }
    }
  }

  async function updateBands(updatedBands) {
    try {
      const response = await fetch('/api/bands', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedBands),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await fetchConfig()
    } catch (err) {
      console.error('Failed to update bands:', err)
      lastError.value = { message: `Bands: ${err.message}`, timestamp: Date.now() }
    }
  }

  async function updateGain(rxGain, rxGainMode) {
    try {
      const response = await fetch('/api/gain', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rx_gain: rxGain, rx_gain_mode: rxGainMode }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await fetchConfig()
    } catch (err) {
      console.error('Failed to update gain:', err)
      lastError.value = { message: `Gain: ${err.message}`, timestamp: Date.now() }
    }
  }

  // Toggle single band enabled state
  function toggleBand(bandName) {
    const updated = bands.value.map(b => ({
      ...b,
      enabled: b.name === bandName ? !b.enabled : b.enabled,
    }))
    updateBands(updated)
  }

  return {
    // State
    config,
    status,
    connected,
    lastError,

    // Computed
    scanning,
    currentBand,
    bands,
    enabledBands,
    settings,

    // Scan data (use getScanData + scanBus for performance)
    getScanData,
    scanUpdateCount,

    // Actions
    connect,
    disconnect,
    fetchConfig,
    fetchStatus,
    startScanning,
    stopScanning,
    updateBands,
    updateGain,
    toggleBand,
  }
})
