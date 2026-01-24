import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useScanData, scanBus } from '@lib'

// Re-export for components that import from store
export { scanBus }

// Wails runtime bindings (injected at runtime)
const wails = window.go?.main?.App

/**
 * Desktop scanner store - uses Wails bindings to communicate with Go backend
 */
export const useDesktopStore = defineStore('desktop', () => {
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
  const status = ref({
    scanning: false,
    current_band: '',
    connected: false,
  })
  const lastError = ref(null)

  // Server mode state
  const serverStatus = ref({
    mqtt_enabled: false,
    mqtt_connected: false,
    mqtt_broker: '',
    web_enabled: false,
    web_port: 8080,
    web_running: false,
  })
  const mqttConfig = ref({
    enabled: false,
    broker: '',
    id: '',
    token: '',
    name: '',
    location: '',
  })
  const webConfig = ref({
    enabled: false,
    port: 8080,
  })
  const configPath = ref('')

  // Computed
  const scanning = computed(() => status.value?.scanning || false)
  const connected = computed(() => status.value?.connected || false)
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

  // Initialize Wails event listeners
  function init() {
    if (!window.runtime) {
      console.warn('Wails runtime not available')
      return
    }

    // Listen for scan events from Go backend
    window.runtime.EventsOn('scan', (data) => {
      handleScanData(data)
    })

    // Listen for status events from Go backend
    window.runtime.EventsOn('status', (data) => {
      status.value = {
        scanning: data.scanning,
        current_band: data.current_band,
        connected: data.connected,
      }
    })

    // Listen for server-status events from Go backend
    window.runtime.EventsOn('server-status', (data) => {
      serverStatus.value = data
    })

    // Fetch initial config
    fetchConfig()
    fetchStatus()
    fetchServerStatus()
    fetchMQTTConfig()
    fetchWebConfig()
    fetchConfigPath()
  }

  // Wails API calls
  async function connect(address = '') {
    if (!wails) {
      lastError.value = { message: 'Wails not available', timestamp: Date.now() }
      return
    }

    try {
      await wails.Connect(address)
      await fetchConfig()
      await fetchStatus()
    } catch (err) {
      console.error('Failed to connect:', err)
      lastError.value = { message: `Connect: ${err}`, timestamp: Date.now() }
    }
  }

  async function disconnect() {
    if (!wails) return
    try {
      await wails.Disconnect()
    } catch (err) {
      console.error('Failed to disconnect:', err)
    }
  }

  async function detectPluto() {
    if (!wails) return ''
    try {
      return await wails.DetectPluto()
    } catch (err) {
      console.error('Failed to detect Pluto:', err)
      return ''
    }
  }

  async function detectDevice() {
    if (!wails) return ''
    try {
      return await wails.DetectDevice()
    } catch (err) {
      console.error('Failed to detect device:', err)
      return ''
    }
  }

  // Get backend type from config
  function getBackendType() {
    return config.value?.backend?.type || 'pluto'
  }

  // Get display name for backend type
  function getBackendDisplayName() {
    const type = getBackendType()
    switch (type) {
      case 'pluto': return 'ADALM-Pluto'
      case 'tinysa': return 'tinySA Ultra'
      case 'owon': return 'OWON HSA'
      default: return type
    }
  }

  // Get default address for backend type
  function getDefaultAddress() {
    const type = getBackendType()
    switch (type) {
      case 'pluto': return 'https://192.168.2.1'
      case 'tinysa': return '/dev/tty.usbmodem4001'
      case 'owon': return '192.168.1.100'
      default: return ''
    }
  }

  async function fetchConfig() {
    if (!wails) return
    try {
      config.value = await wails.GetConfig()
    } catch (err) {
      console.error('Failed to fetch config:', err)
    }
  }

  async function fetchStatus() {
    if (!wails) return
    try {
      const s = await wails.GetStatus()
      status.value = s
    } catch (err) {
      console.error('Failed to fetch status:', err)
    }
  }

  async function startScanning() {
    if (!wails) return
    try {
      await wails.StartScanning()
    } catch (err) {
      console.error('Failed to start scanning:', err)
      lastError.value = { message: `Start: ${err}`, timestamp: Date.now() }
    }
  }

  async function stopScanning() {
    if (!wails) return
    try {
      await wails.StopScanning()
    } catch (err) {
      console.error('Failed to stop scanning:', err)
      lastError.value = { message: `Stop: ${err}`, timestamp: Date.now() }
    }
  }

  async function toggleBand(bandName) {
    if (!wails || !config.value) return
    const band = config.value.bands.find(b => b.name === bandName)
    if (band) {
      try {
        await wails.SetBandEnabled(bandName, !band.enabled)
        await fetchConfig()
      } catch (err) {
        console.error('Failed to toggle band:', err)
      }
    }
  }

  async function updateGain(rxGain, rxGainMode) {
    if (!wails) return
    try {
      await wails.SetGain(rxGain, rxGainMode)
      await fetchConfig()
    } catch (err) {
      console.error('Failed to update gain:', err)
      lastError.value = { message: `Gain: ${err}`, timestamp: Date.now() }
    }
  }

  async function updateName(name) {
    if (!wails) return
    try {
      await wails.SetName(name)
      await fetchConfig()
    } catch (err) {
      console.error('Failed to update name:', err)
      lastError.value = { message: `Name: ${err}`, timestamp: Date.now() }
    }
  }

  // ============================================================================
  // Server Mode Actions
  // ============================================================================

  async function fetchServerStatus() {
    if (!wails) return
    try {
      serverStatus.value = await wails.GetServerStatus()
    } catch (err) {
      console.error('Failed to fetch server status:', err)
    }
  }

  async function fetchMQTTConfig() {
    if (!wails) return
    try {
      const cfg = await wails.GetMQTTConfig()
      mqttConfig.value = {
        enabled: cfg.enabled || false,
        broker: cfg.broker || '',
        id: cfg.id || '',
        token: cfg.token || '',
        name: cfg.name || '',
        location: cfg.location || '',
      }
    } catch (err) {
      console.error('Failed to fetch MQTT config:', err)
    }
  }

  async function fetchWebConfig() {
    if (!wails) return
    try {
      const cfg = await wails.GetWebConfig()
      webConfig.value = {
        enabled: cfg.enabled || false,
        port: cfg.port || 8080,
      }
    } catch (err) {
      console.error('Failed to fetch web config:', err)
    }
  }

  async function fetchConfigPath() {
    if (!wails) return
    try {
      configPath.value = await wails.GetConfigPath()
    } catch (err) {
      console.error('Failed to fetch config path:', err)
    }
  }

  async function setMQTTConfig(cfg) {
    if (!wails) return
    try {
      await wails.SetMQTTConfig(
        cfg.enabled,
        cfg.broker,
        cfg.id,
        cfg.token,
        cfg.location
      )
      mqttConfig.value = cfg
    } catch (err) {
      console.error('Failed to set MQTT config:', err)
      lastError.value = { message: `MQTT config: ${err}`, timestamp: Date.now() }
    }
  }

  async function setWebConfig(cfg) {
    if (!wails) return
    try {
      await wails.SetWebConfig(cfg.enabled, cfg.port)
      webConfig.value = cfg
    } catch (err) {
      console.error('Failed to set web config:', err)
      lastError.value = { message: `Web config: ${err}`, timestamp: Date.now() }
    }
  }

  async function enableMQTT() {
    if (!wails) return
    try {
      await wails.EnableMQTT()
      await fetchServerStatus()
    } catch (err) {
      console.error('Failed to enable MQTT:', err)
      lastError.value = { message: `Enable MQTT: ${err}`, timestamp: Date.now() }
    }
  }

  async function disableMQTT() {
    if (!wails) return
    try {
      await wails.DisableMQTT()
      await fetchServerStatus()
    } catch (err) {
      console.error('Failed to disable MQTT:', err)
      lastError.value = { message: `Disable MQTT: ${err}`, timestamp: Date.now() }
    }
  }

  async function enableWebServer() {
    if (!wails) return
    try {
      await wails.EnableWebServer()
      await fetchServerStatus()
    } catch (err) {
      console.error('Failed to enable web server:', err)
      lastError.value = { message: `Enable web: ${err}`, timestamp: Date.now() }
    }
  }

  async function disableWebServer() {
    if (!wails) return
    try {
      await wails.DisableWebServer()
      await fetchServerStatus()
    } catch (err) {
      console.error('Failed to disable web server:', err)
      lastError.value = { message: `Disable web: ${err}`, timestamp: Date.now() }
    }
  }

  async function saveConfig() {
    if (!wails) return
    try {
      await wails.SaveConfig()
    } catch (err) {
      console.error('Failed to save config:', err)
      lastError.value = { message: `Save config: ${err}`, timestamp: Date.now() }
    }
  }

  return {
    // State
    config,
    status,
    lastError,
    serverStatus,
    mqttConfig,
    webConfig,
    configPath,

    // Computed
    scanning,
    connected,
    currentBand,
    bands,
    enabledBands,
    settings,

    // Scan data (use getScanData + scanBus for performance)
    getScanData,
    scanUpdateCount,
    clearScanData,
    getScanInfo,
    generateCSV,
    downloadCSV,

    // Actions
    init,
    connect,
    disconnect,
    detectPluto,
    detectDevice,
    getBackendType,
    getBackendDisplayName,
    getDefaultAddress,
    fetchConfig,
    fetchStatus,
    startScanning,
    stopScanning,
    toggleBand,
    updateGain,
    updateName,

    // Server mode actions
    fetchServerStatus,
    fetchMQTTConfig,
    fetchWebConfig,
    setMQTTConfig,
    setWebConfig,
    enableMQTT,
    disableMQTT,
    enableWebServer,
    disableWebServer,
    saveConfig,
  }
})
