import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import mqtt from 'mqtt'

export const useScannersStore = defineStore('scanners', () => {
  const scanners = ref({})
  const latestScans = ref({})       // { scannerId: lastScan }
  const bandScans = ref({})         // { scannerId: { bandName: lastScan } }
  const timelines = ref({})         // { `${scannerId}:${bandName}`: [{ id, timestamp, band__name }] }
  const scanCache = ref({})         // { `${scannerId}:${bandName}`: [{ timestamp, scan }, ...] } - historical scans
  const connected = ref(false)
  const subscriptions = ref(new Set()) // Track subscribed scanner IDs
  let client = null
  let reconnectTimeout = null

  const scannerList = computed(() => Object.values(scanners.value))

  // MQTT topic prefix
  const TOPIC_PREFIX = 'spectrum'

  function getMqttUrl() {
    // In Docker, connect to mosquitto service on port 9001
    // In dev, connect to localhost:9001
    const host = window.location.hostname
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // Use port 9001 for MQTT over WebSocket
    return `${protocol}//${host}:9001`
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
    })

    client.on('reconnect', () => {
      console.log('MQTT reconnecting...')
    })
  }

  function disconnect() {
    if (client) {
      client.end()
      client = null
    }
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
  async function loadScanCache(scannerId, bandName, hours = 0.167) {
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

  // Fetch timeline data for time scrubber (also populates the store)
  async function fetchTimeline(scannerId, bandName = null, hours = 24) {
    try {
      let url = `/api/scanners/${scannerId}/timeline/?hours=${hours}`
      if (bandName) {
        url += `&band=${encodeURIComponent(bandName)}`
      }
      const response = await fetch(url, {
        credentials: 'include',
      })
      if (!response.ok) throw new Error('Failed to fetch timeline')
      const data = await response.json()

      // Store in the reactive timelines object
      const key = `${scannerId}:${bandName || 'default'}`
      timelines.value[key] = data

      return data
    } catch (error) {
      console.error('Failed to fetch timeline:', error)
      return []
    }
  }

  // Fetch historical scan data
  async function fetchHistory(scannerId, bandName = null, hours = 24, limit = 1000) {
    try {
      let url = `/api/scanners/${scannerId}/history/?hours=${hours}&limit=${limit}`
      if (bandName) {
        url += `&band=${encodeURIComponent(bandName)}`
      }
      const response = await fetch(url, {
        credentials: 'include',
      })
      if (!response.ok) throw new Error('Failed to fetch history')
      return await response.json()
    } catch (error) {
      console.error('Failed to fetch history:', error)
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
      if (!response.ok) throw new Error('Failed to fetch scan')
      return await response.json()
    } catch (error) {
      console.error('Failed to fetch scan at time:', error)
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
  }
})
