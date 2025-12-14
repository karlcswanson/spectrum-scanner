import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import mqtt from 'mqtt'
import { SCRUBBER_HOURS } from '../constants'

export const useScannersStore = defineStore('scanners', () => {
  const scanners = ref({})
  const latestScans = ref({})       // { scannerId: lastScan }
  const bandScans = ref({})         // { scannerId: { bandName: lastScan } }
  const timelines = ref({})         // { `${scannerId}:${bandName}`: [{ id, timestamp, band__name }] }
  const scanCache = ref({})         // { `${scannerId}:${bandName}`: [{ timestamp, scan }, ...] } - historical scans
  const decimatedCache = ref({})    // { `${scannerId}:${bandName}`: [{ timestamp, scan }, ...] } - decimated scans for scrubbing
  const connected = ref(false)
  const lastError = ref(null)       // { message, timestamp } - most recent error
  const apiErrors = ref(0)          // Count of API errors (resets on success)

  // Global tick for timeline redraws (updates every 500ms)
  const tick = ref(0)
  let tickInterval = null

  function startTick() {
    if (!tickInterval) {
      tickInterval = setInterval(() => {
        tick.value++
      }, 500)
    }
  }

  function stopTick() {
    if (tickInterval) {
      clearInterval(tickInterval)
      tickInterval = null
    }
  }
  const subscriptions = ref(new Set()) // Track subscribed scanner IDs
  let client = null
  let reconnectTimeout = null

  const scannerList = computed(() => Object.values(scanners.value))

  // MQTT topic prefix
  const TOPIC_PREFIX = 'spectrum'

  function getMqttUrl() {
    const host = window.location.hostname
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const port = window.location.port

    // In production (via Caddy), use /mqtt path on same host
    // In development, connect directly to mosquitto on port 9001
    if (import.meta.env.PROD) {
      // Production: WebSocket through Caddy reverse proxy
      const portPart = port ? `:${port}` : ''
      return `${protocol}//${host}${portPart}/mqtt`
    } else {
      // Development: direct connection to mosquitto
      return `${protocol}//${host}:9001`
    }
  }

  async function fetchMqttCredentials() {
    try {
      const response = await fetch('/api/mqtt/credentials/', {
        credentials: 'include',
      })
      if (!response.ok) throw new Error('Failed to fetch MQTT credentials')
      return await response.json()
    } catch (error) {
      console.error('Failed to fetch MQTT credentials:', error)
      return null
    }
  }

  async function connect() {
    // Prevent multiple connections
    if (client && client.connected) {
      return
    }

    // Fetch credentials from Django
    const credentials = await fetchMqttCredentials()
    if (!credentials) {
      console.error('Could not get MQTT credentials')
      return
    }

    const mqttUrl = getMqttUrl()
    console.log('Connecting to MQTT:', mqttUrl)

    client = mqtt.connect(mqttUrl, {
      clientId: `spectrum-frontend-${Math.random().toString(16).substring(2, 10)}`,
      username: credentials.username,
      password: credentials.password,
      clean: true,
      reconnectPeriod: 2000,
      connectTimeout: 10000,
    })

    client.on('connect', () => {
      console.log('MQTT connected')
      connected.value = true

      // Start the global tick timer
      startTick()

      // Subscribe to all scanner topics (config, status, scan, timeline)
      // Using wildcard to get all scanners
      client.subscribe(`${TOPIC_PREFIX}/scanners/+/config`, { qos: 1 })
      client.subscribe(`${TOPIC_PREFIX}/scanners/+/status`, { qos: 1 })
      client.subscribe(`${TOPIC_PREFIX}/scanners/+/scan`, { qos: 0 })
      client.subscribe(`${TOPIC_PREFIX}/scanners/+/timeline`, { qos: 0 })

      console.log('Subscribed to scanner topics')
    })

    client.on('message', (topic, payload) => {
      try {
        const message = JSON.parse(payload.toString())
        const parts = topic.split('/')
        // Topic format: spectrum/scanners/{scanner_id}/{type}
        if (parts.length >= 4 && parts[0] === TOPIC_PREFIX && parts[1] === 'scanners') {
          const scannerId = parts[2]
          const messageType = parts[3]

          if (messageType === 'scan') {
            handleScan(scannerId, message)
          } else if (messageType === 'status') {
            handleStatus(scannerId, message)
          } else if (messageType === 'config') {
            handleConfig(scannerId, message)
          } else if (messageType === 'timeline') {
            handleTimeline(scannerId, message)
          }
        }
      } catch (error) {
        console.error('Failed to parse MQTT message:', error)
      }
    })

    client.on('close', () => {
      console.log('MQTT disconnected')
      connected.value = false
    })

    client.on('error', (error) => {
      console.error('MQTT error:', error)
      lastError.value = { message: `MQTT: ${error.message || error}`, timestamp: Date.now() }
    })

    client.on('reconnect', () => {
      console.log('MQTT reconnecting...')
      lastError.value = { message: 'MQTT reconnecting...', timestamp: Date.now() }
    })
  }

  function disconnect() {
    if (client) {
      client.end()
      client = null
    }
    stopTick()
    connected.value = false
  }

  // Subscribe/unsubscribe are now no-ops since we use wildcard subscription
  // Keep the API for compatibility with existing components
  function subscribe(scannerId) {
    if (!scannerId) return
    subscriptions.value.add(scannerId)
    console.log('Tracking scanner:', scannerId)
  }

  function unsubscribe(scannerId) {
    if (!scannerId) return
    subscriptions.value.delete(scannerId)
    console.log('Untracking scanner:', scannerId)
  }

  function handleScan(scannerId, data) {
    // Create scanner entry if it doesn't exist
    if (!scanners.value[scannerId]) {
      scanners.value[scannerId] = {
        id: scannerId,
        name: scannerId,
        type: 'unknown',
        location: '',
        online: true,
      }
    }
    scanners.value[scannerId].online = true
    scanners.value[scannerId].lastSeen = new Date()

    // Store latest scan with receive timestamp
    const scanWithTime = { ...data, _receivedAt: Date.now() }
    latestScans.value[scannerId] = scanWithTime

    // Also store by band name if available
    if (data.band) {
      if (!bandScans.value[scannerId]) {
        bandScans.value[scannerId] = {}
      }
      bandScans.value[scannerId][data.band] = scanWithTime

      // Auto-populate bands from scan data if not already present
      if (!scanners.value[scannerId].bands) {
        scanners.value[scannerId].bands = []
      }
      const existingBand = scanners.value[scannerId].bands.find(b => b.name === data.band)
      if (!existingBand) {
        scanners.value[scannerId].bands.push({
          name: data.band,
          start_hz: data.hz_lo,
          stop_hz: data.hz_hi,
          enabled: true,
        })
      }
    }
  }

  function handleStatus(scannerId, data) {
    if (!scanners.value[scannerId]) {
      scanners.value[scannerId] = { id: scannerId, name: scannerId }
    }
    scanners.value[scannerId] = {
      ...scanners.value[scannerId],
      id: scannerId,
      online: data.online,
      scanning: data.scanning,
      current_band: data.current_band,
    }
  }

  function handleConfig(scannerId, data) {
    console.log('handleConfig:', scannerId, 'bands:', data.bands)
    scanners.value[scannerId] = {
      ...scanners.value[scannerId],
      id: scannerId,
      name: data.name || scannerId,
      scanner_type: data.type || 'unknown',
      location: data.location || '',
      description: data.description || '',
      bands: data.bands || [],
      settings: data.settings || {},
      online: true,
    }
  }

  function handleTimeline(scannerId, data) {
    // Timeline update from Django - a new scan was stored in the database
    // Format: { id, timestamp, band__name, scan?: { hz_lo, hz_hi, step_hz, power } }
    const bandName = data.band__name || 'default'
    const key = `${scannerId}:${bandName}`

    // Initialize timeline array if needed
    if (!timelines.value[key]) {
      timelines.value[key] = []
    }

    // Append the new entry (avoid duplicates by id)
    const exists = timelines.value[key].some(t => t.id === data.id)
    if (!exists) {
      // Create new array to trigger Vue reactivity
      const updated = [...timelines.value[key], data]
        .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))

      // Limit to last 24 hours worth of entries (rough estimate: ~8640 at 10s interval)
      const maxEntries = 10000
      timelines.value[key] = updated.length > maxEntries
        ? updated.slice(-maxEntries)
        : updated
    }

    // Add scan data to cache if included
    if (data.scan) {
      if (!scanCache.value[key]) {
        scanCache.value[key] = []
      }

      const scanExists = scanCache.value[key].some(s => s.id === data.id)
      if (!scanExists) {
        const timestampMs = new Date(data.timestamp).getTime()
        const cacheEntry = {
          id: data.id,
          timestamp: timestampMs,
          scan: {
            hz_lo: data.scan.hz_lo,
            hz_hi: data.scan.hz_hi,
            step: data.scan.step_hz,
            power: data.scan.power,
            timestamp: data.timestamp,
          }
        }

        // Insert in sorted order
        const insertIdx = scanCache.value[key].findIndex(s => s.timestamp > timestampMs)
        if (insertIdx === -1) {
          scanCache.value[key] = [...scanCache.value[key], cacheEntry]
        } else {
          const updated = [...scanCache.value[key]]
          updated.splice(insertIdx, 0, cacheEntry)
          scanCache.value[key] = updated
        }

        // Limit cache size (keep last ~10 min at 10s intervals = ~60 entries per scanner)
        const maxCacheEntries = 100
        if (scanCache.value[key].length > maxCacheEntries) {
          scanCache.value[key] = scanCache.value[key].slice(-maxCacheEntries)
        }
      }
    }
  }

  // Get timeline for a scanner/band (reactive)
  // Returns the reactive array directly so Vue can track changes
  function getTimeline(scannerId, bandName = 'default') {
    const key = `${scannerId}:${bandName}`
    // Initialize if needed so we return a stable reactive reference
    if (!timelines.value[key]) {
      timelines.value[key] = []
    }
    return timelines.value[key]
  }

  // Get scan cache for a scanner/band
  function getScanCache(scannerId, bandName = 'default') {
    const key = `${scannerId}:${bandName}`
    if (!scanCache.value[key]) {
      scanCache.value[key] = []
    }
    return scanCache.value[key]
  }

  // Find closest scan in cache (binary search)
  function findScanInCache(scannerId, bandName, targetTime) {
    const key = `${scannerId}:${bandName}`
    const cache = scanCache.value[key]
    if (!cache || cache.length === 0) return null

    const targetMs = targetTime.getTime()

    // Binary search for closest
    let left = 0
    let right = cache.length - 1

    while (left < right) {
      const mid = Math.floor((left + right) / 2)
      if (cache[mid].timestamp < targetMs) {
        left = mid + 1
      } else {
        right = mid
      }
    }

    // Check left and left-1 to find closest
    const candidates = []
    if (left < cache.length) candidates.push(cache[left])
    if (left > 0) candidates.push(cache[left - 1])

    let closest = null
    let closestDiff = Infinity
    for (const c of candidates) {
      const diff = Math.abs(c.timestamp - targetMs)
      if (diff < closestDiff) {
        closestDiff = diff
        closest = c
      }
    }

    return closest?.scan || null
  }

  // Load scan cache from API (for initial load)
  async function loadScanCache(scannerId, bandName, hours = SCRUBBER_HOURS) {
    const key = `${scannerId}:${bandName}`
    try {
      const scans = await fetchHistory(scannerId, bandName, hours, 1000)
      if (scans && scans.length > 0) {
        scanCache.value[key] = scans.map(s => ({
          id: s.id,
          timestamp: new Date(s.timestamp).getTime(),
          scan: {
            hz_lo: s.hz_lo,
            hz_hi: s.hz_hi,
            step: s.step_hz,
            power: s.power,
            timestamp: s.timestamp,
          }
        })).sort((a, b) => a.timestamp - b.timestamp)
      } else {
        scanCache.value[key] = []
      }
      return scanCache.value[key]
    } catch (err) {
      console.error(`Error loading cache for ${scannerId}/${bandName}:`, err)
      scanCache.value[key] = []
      return []
    }
  }

  // Load decimated cache from API (for scrubber preview)
  // Accepts either hours (number) or options object { hours, start, end }
  async function loadDecimatedCache(scannerId, bandName, options = SCRUBBER_HOURS) {
    const key = `${scannerId}:${bandName}`
    try {
      // Build options for fetchHistory
      let fetchOpts
      if (typeof options === 'number') {
        fetchOpts = { hours: options, limit: 1000, decimated: true }
      } else if (options && typeof options === 'object') {
        // Has start/end dates (custom range) or hours (preset)
        if (options.start && options.end) {
          fetchOpts = {
            start: options.start,
            end: options.end,
            limit: 1000,
            decimated: true,
          }
        } else {
          fetchOpts = {
            hours: options.hours || 24,
            limit: 1000,
            decimated: true,
          }
        }
      } else {
        // Fallback
        fetchOpts = { hours: 24, limit: 1000, decimated: true }
      }
      const scans = await fetchHistory(scannerId, bandName, fetchOpts)
      if (scans && scans.length > 0) {
        decimatedCache.value[key] = scans.map(s => ({
          id: s.id,
          timestamp: new Date(s.timestamp).getTime(),
          scan: {
            hz_lo: s.hz_lo,
            hz_hi: s.hz_hi,
            step: s.step_hz,
            power: s.power,
            timestamp: s.timestamp,
          }
        })).sort((a, b) => a.timestamp - b.timestamp)
      } else {
        decimatedCache.value[key] = []
      }
      return decimatedCache.value[key]
    } catch (err) {
      console.error(`Error loading decimated cache for ${scannerId}/${bandName}:`, err)
      decimatedCache.value[key] = []
      return []
    }
  }

  // Find closest scan in decimated cache (binary search)
  function findScanInDecimatedCache(scannerId, bandName, targetTime) {
    const key = `${scannerId}:${bandName}`
    const cache = decimatedCache.value[key]
    if (!cache || cache.length === 0) return null

    const targetMs = targetTime.getTime()

    // Binary search for closest
    let left = 0
    let right = cache.length - 1

    while (left < right) {
      const mid = Math.floor((left + right) / 2)
      if (cache[mid].timestamp < targetMs) {
        left = mid + 1
      } else {
        right = mid
      }
    }

    // Check left and left-1 to find closest
    const candidates = []
    if (left < cache.length) candidates.push(cache[left])
    if (left > 0) candidates.push(cache[left - 1])

    let closest = null
    let closestDiff = Infinity
    for (const c of candidates) {
      const diff = Math.abs(c.timestamp - targetMs)
      if (diff < closestDiff) {
        closestDiff = diff
        closest = c
      }
    }

    return closest?.scan || null
  }

  // Clear decimated cache (when switching views)
  function clearDecimatedCache(scannerId = null, bandName = null) {
    if (scannerId && bandName) {
      const key = `${scannerId}:${bandName}`
      delete decimatedCache.value[key]
    } else {
      decimatedCache.value = {}
    }
  }

  async function fetchScanners() {
    try {
      const response = await fetch('/api/scanners/', {
        credentials: 'include',
      })
      const data = await response.json()
      data.forEach(scanner => {
        scanners.value[scanner.id] = {
          ...scanners.value[scanner.id],
          ...scanner,
        }
      })
    } catch (error) {
      console.error('Failed to fetch scanners:', error)
    }
  }

  // Generate WWB-compatible CSV from scan data
  function generateCSV(scan) {
    if (!scan || !scan.power) return ''

    let csv = 'Frequency (MHz),Power (dBm)\n'
    const startMHz = scan.hz_lo / 1e6
    const stepMHz = scan.step / 1e6

    for (let i = 0; i < scan.power.length; i++) {
      const freq = startMHz + (i * stepMHz)
      csv += `${freq.toFixed(6)},${scan.power[i].toFixed(2)}\n`
    }
    return csv
  }

  // Export scan data as CSV file
  function exportScanCSV(scannerId, bandName) {
    const scan = bandScans.value[scannerId]?.[bandName]
    if (!scan) {
      console.error('No scan data for', scannerId, bandName)
      return
    }

    const csv = generateCSV(scan)
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)

    const scannerName = scanners.value[scannerId]?.name || scannerId
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const filename = `${scannerName.replace(/\s+/g, '-')}_${bandName.replace(/\s+/g, '-')}_${timestamp}.csv`

    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()

    URL.revokeObjectURL(url)
    console.log('Exported:', filename)
  }

  // Helper for API calls with error tracking
  function setApiError(message) {
    apiErrors.value++
    lastError.value = { message: `API: ${message}`, timestamp: Date.now() }
  }

  function clearApiError() {
    apiErrors.value = 0
  }

  // Fetch timeline data for time scrubber (also populates the store)
  // Supports either relative hours or absolute start/end dates
  async function fetchTimeline(scannerId, bandName = null, options = {}) {
    try {
      // Support both old signature (hours as number) and new signature (options object)
      let hours, startDate, endDate
      if (typeof options === 'number') {
        hours = options
      } else {
        hours = options.hours
        startDate = options.start
        endDate = options.end
      }

      let url = `/api/scanners/${scannerId}/timeline/?`
      if (startDate) {
        url += `start=${startDate.toISOString()}`
        if (endDate) {
          url += `&end=${endDate.toISOString()}`
        }
      } else {
        url += `hours=${hours || 24}`
      }
      if (bandName) {
        url += `&band=${encodeURIComponent(bandName)}`
      }
      const response = await fetch(url, {
        credentials: 'include',
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()

      // Store in the reactive timelines object
      const key = `${scannerId}:${bandName || 'default'}`
      timelines.value[key] = data
      clearApiError()

      return data
    } catch (error) {
      console.error('Failed to fetch timeline:', error)
      setApiError(`Timeline: ${error.message}`)
      return []
    }
  }

  // Fetch historical scan data
  // Supports either relative hours or absolute start/end dates
  async function fetchHistory(scannerId, bandName = null, options = {}) {
    try {
      // Support both old signature and new signature
      let hours, limit, decimated, startDate, endDate
      if (typeof options === 'number') {
        hours = options
        limit = arguments[3] || 1000
        decimated = arguments[4] || false
      } else {
        hours = options.hours
        limit = options.limit || 1000
        decimated = options.decimated || false
        startDate = options.start
        endDate = options.end
      }

      let url = `/api/scanners/${scannerId}/history/?limit=${limit}`
      if (startDate) {
        url += `&start=${startDate.toISOString()}`
        if (endDate) {
          url += `&end=${endDate.toISOString()}`
        }
      } else {
        url += `&hours=${hours || 24}`
      }
      if (bandName) {
        url += `&band=${encodeURIComponent(bandName)}`
      }
      if (decimated) {
        url += '&decimated=true'
      }
      const response = await fetch(url, {
        credentials: 'include',
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      clearApiError()
      return await response.json()
    } catch (error) {
      console.error('Failed to fetch history:', error)
      setApiError(`History: ${error.message}`)
      return []
    }
  }

  // Fetch scan closest to a specific time
  async function fetchScanAtTime(scannerId, time, bandName = null) {
    try {
      let url = `/api/scans/at_time/?scanner=${scannerId}&time=${time.toISOString()}`
      if (bandName) {
        url += `&band=${encodeURIComponent(bandName)}`
      }
      const response = await fetch(url, {
        credentials: 'include',
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      clearApiError()
      return await response.json()
    } catch (error) {
      console.error('Failed to fetch scan at time:', error)
      setApiError(`Scan: ${error.message}`)
      return null
    }
  }

  return {
    scanners,
    scannerList,
    latestScans,
    bandScans,
    timelines,
    scanCache,
    decimatedCache,
    connected,
    connect,
    disconnect,
    subscribe,
    unsubscribe,
    fetchScanners,
    exportScanCSV,
    fetchTimeline,
    getTimeline,
    fetchHistory,
    fetchScanAtTime,
    getScanCache,
    findScanInCache,
    loadScanCache,
    loadDecimatedCache,
    findScanInDecimatedCache,
    clearDecimatedCache,
    tick,
    lastError,
    apiErrors,
  }
})
