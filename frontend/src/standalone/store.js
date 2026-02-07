import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { useScanData, scanBus, logger } from '@lib'

// Re-export for components that import from store
export { scanBus }

// Detect Wails desktop app - use localhost:8080 for API
const isWails = !!(window.wails || window.go)
const apiBase = isWails ? 'http://localhost:8080' : ''

/**
 * Standalone scanner store - connects directly to Go scanner API
 * No MQTT, no auth - just local WebSocket and REST API
 */
export const useStandaloneStore = defineStore('standalone', () => {
  // Shared scan data management
  const {
    scanUpdateCount,
    handleScanData,
    getScanData,
    clearScanData,
    getScanInfo,
    generateCSV,
    downloadCSV,
  } = useScanData()

  // Scanner state
  const config = ref(null)
  const status = ref(null)
  const connected = ref(false)
  const lastError = ref(null)

  // Server mode state (for MQTT and web server control)
  const serverStatus = ref({
    mqtt_enabled: false,
    mqtt_connected: false,
    mqtt_broker: '',
    web_enabled: false,
    web_port: 8080,
    web_running: false,
  })

  // Computed from config
  const mqttConfig = computed(() => config.value?.mqtt || {})
  const webConfig = computed(() => config.value?.web || { port: 8080 })

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
    const host = isWails ? 'localhost:8080' : window.location.host
    const wsUrl = `${protocol}//${host}/ws/stream`

    logger.debug('Connecting to WebSocket:', wsUrl)
    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      logger.debug('WebSocket connected')
      connected.value = true
      lastError.value = null
      // Fetch initial config
      fetchConfig()
      fetchStatus()
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        // Handle typed messages: { type: "scan" | "status" | "config", data: {...} }
        if (msg.type === 'scan') {
          handleScanData(msg.data)
        } else if (msg.type === 'status') {
          handleStatusUpdate(msg.data)
        } else if (msg.type === 'config') {
          // Config pushed from server (e.g., remote MQTT command)
          config.value = msg.data
        } else {
          // Legacy format (raw scan data)
          handleScanData(msg)
        }
      } catch (err) {
        logger.error('Failed to parse WebSocket message:', err)
      }
    }

    ws.onclose = () => {
      logger.debug('WebSocket disconnected')
      connected.value = false
      // Reconnect after delay
      reconnectTimeout = setTimeout(connect, 2000)
    }

    ws.onerror = () => {
      logger.error('WebSocket connection error')
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
      const response = await fetch(`${apiBase}/api/config`)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      config.value = await response.json()
    } catch (err) {
      lastError.value = { message: `Config: ${err.message}`, timestamp: Date.now() }
    }
  }

  async function fetchStatus() {
    try {
      const response = await fetch(`${apiBase}/api/status`)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      status.value = await response.json()
    } catch (err) {
      // Status fetch errors are non-critical
    }
  }

  async function startScanning() {
    try {
      const response = await fetch(`${apiBase}/api/scan/start`, { method: 'POST' })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await fetchStatus()
    } catch (err) {
      lastError.value = { message: `Start: ${err.message}`, timestamp: Date.now() }
    }
  }

  async function stopScanning() {
    try {
      const response = await fetch(`${apiBase}/api/scan/stop`, { method: 'POST' })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await fetchStatus()
    } catch (err) {
      lastError.value = { message: `Stop: ${err.message}`, timestamp: Date.now() }
    }
  }

  async function updateBands(updatedBands) {
    try {
      const response = await fetch(`${apiBase}/api/bands`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedBands),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await fetchConfig()
    } catch (err) {
      lastError.value = { message: `Bands: ${err.message}`, timestamp: Date.now() }
    }
  }

  async function updateGain(rxGain, rxGainMode) {
    try {
      const response = await fetch(`${apiBase}/api/gain`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rx_gain: rxGain, rx_gain_mode: rxGainMode }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await fetchConfig()
    } catch (err) {
      lastError.value = { message: `Gain: ${err.message}`, timestamp: Date.now() }
    }
  }

  async function updateName(name) {
    try {
      const response = await fetch(`${apiBase}/api/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await fetchConfig()
    } catch (err) {
      lastError.value = { message: `Name: ${err.message}`, timestamp: Date.now() }
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

  // Server mode control (uses Wails bindings if available)
  const wailsApp = window.go?.main?.App

  async function setMQTTConfig(cfg) {
    if (wailsApp?.SetMQTTConfig) {
      try {
        await wailsApp.SetMQTTConfig(cfg)
      } catch (err) {
        lastError.value = { message: `MQTT Config: ${err.message}`, timestamp: Date.now() }
      }
    }
  }

  async function setWebConfig(cfg) {
    if (wailsApp?.SetWebConfig) {
      try {
        await wailsApp.SetWebConfig(cfg)
      } catch (err) {
        lastError.value = { message: `Web Config: ${err.message}`, timestamp: Date.now() }
      }
    }
  }

  async function enableMQTT() {
    if (wailsApp?.EnableMQTT) {
      try {
        await wailsApp.EnableMQTT()
      } catch (err) {
        lastError.value = { message: `MQTT: ${err.message}`, timestamp: Date.now() }
      }
    }
  }

  async function disableMQTT() {
    if (wailsApp?.DisableMQTT) {
      try {
        await wailsApp.DisableMQTT()
      } catch (err) {
        lastError.value = { message: `MQTT: ${err.message}`, timestamp: Date.now() }
      }
    }
  }

  async function enableWebServer() {
    if (wailsApp?.EnableWebServer) {
      try {
        await wailsApp.EnableWebServer()
      } catch (err) {
        lastError.value = { message: `Web Server: ${err.message}`, timestamp: Date.now() }
      }
    }
  }

  async function disableWebServer() {
    if (wailsApp?.DisableWebServer) {
      try {
        await wailsApp.DisableWebServer()
      } catch (err) {
        lastError.value = { message: `Web Server: ${err.message}`, timestamp: Date.now() }
      }
    }
  }

  // Listen for Wails events (server status updates)
  if (window.runtime) {
    window.runtime.EventsOn('server-status', (data) => {
      serverStatus.value = data
    })
  }

  return {
    // State
    config,
    status,
    connected,
    lastError,
    serverStatus,

    // Computed
    scanning,
    currentBand,
    bands,
    enabledBands,
    settings,
    mqttConfig,
    webConfig,

    // Scan data (use getScanData + scanBus for performance)
    getScanData,
    scanUpdateCount,
    clearScanData,
    getScanInfo,
    generateCSV,
    downloadCSV,

    // Actions
    connect,
    disconnect,
    fetchConfig,
    fetchStatus,
    startScanning,
    stopScanning,
    updateBands,
    updateGain,
    updateName,
    toggleBand,

    // Server mode control
    setMQTTConfig,
    setWebConfig,
    enableMQTT,
    disableMQTT,
    enableWebServer,
    disableWebServer,
  }
})
