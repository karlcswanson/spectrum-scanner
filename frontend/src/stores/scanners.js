import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { SCRUBBER_HOURS } from '../constants'
import { logger, MqttClient, TOPIC_PREFIX } from '../lib'

export const useScannersStore = defineStore('scanners', () => {
  const scanners = ref({})
  const groups = ref([])             // Scanner group list from API
  const monitoredFreqs = ref({})    // { scannerId: [{ id, frequency_hz, frequency_mhz, name, color, category, ... }] }
  const latestScans = ref({})       // { scannerId: lastScan }
  const bandScans = ref({})         // { scannerId: { bandName: lastScan } }
  const timelines = ref({})         // { `${scannerId}:${bandName}`: [{ id, timestamp, band__name }] }
  const scanCache = ref({})         // { `${scannerId}:${bandName}`: [{ timestamp, scan }, ...] } - historical scans
  const decimatedCache = ref({})    // { `${scannerId}:${bandName}`: [{ timestamp, scan }, ...] } - decimated scans for scrubbing
  const connected = ref(false)
  const lastError = ref(null)       // { message, timestamp } - most recent error
  const apiErrors = ref(0)          // Count of API errors (resets on success)
  // Solo is computed: scanner has >1 band but only 1 enabled

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

  let mqttClient = null
  const _subscriptionRefs = {}

  const scannerList = computed(() => Object.values(scanners.value))

  function subscribe(scannerId) {
    if (!scannerId) return
    _subscriptionRefs[scannerId] = (_subscriptionRefs[scannerId] || 0) + 1
    if (_subscriptionRefs[scannerId] === 1) {
      mqttClient?.subscribe(scannerId)
    }
  }

  function unsubscribe(scannerId) {
    if (!scannerId) return
    if (!_subscriptionRefs[scannerId]) return
    _subscriptionRefs[scannerId]--
    if (_subscriptionRefs[scannerId] <= 0) {
      delete _subscriptionRefs[scannerId]
      mqttClient?.unsubscribe(scannerId)
    }
  }

  function handleMessage(topic, payload) {
    try {
      const message = JSON.parse(payload.toString())
      const parts = topic.split('/')
      // Topic format: spectrum/scanners/{scanner_id}/{type}
      if (parts.length >= 4 && parts[0] === TOPIC_PREFIX && parts[1] === 'scanners') {
        const scannerId = parts[2]
        const messageType = parts[3]

        // Only process messages for scanners we're subscribed to
        if (!mqttClient || !mqttClient.subscriptions.has(scannerId)) return

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
      logger.error('Failed to parse MQTT message:', error)
    }
  }

  async function connect() {
    if (!mqttClient) {
      mqttClient = new MqttClient()

      mqttClient.onMessage(handleMessage)
      mqttClient.onStateChange((isConnected) => {
        connected.value = isConnected
        if (isConnected) {
          startTick()
        }
      })
      mqttClient.onError((error) => {
        lastError.value = { message: `MQTT: ${error.message || error}`, timestamp: Date.now() }
      })
    }

    await mqttClient.connect()
  }

  function disconnect() {
    if (mqttClient) {
      mqttClient.disconnect()
      mqttClient = null
    }
    Object.keys(_subscriptionRefs).forEach(k => delete _subscriptionRefs[k])
    stopTick()
    connected.value = false
  }

  // ============== Scanner Command Functions ==============

  function sendStartCommand(scannerId) {
    const topic = `${TOPIC_PREFIX}/commands/${scannerId}/start`
    const ok = mqttClient?.publish(topic, JSON.stringify({}), { qos: 1 })
    if (ok) logger.debug('Sent start command to', scannerId)
    return !!ok
  }

  function sendStopCommand(scannerId) {
    const topic = `${TOPIC_PREFIX}/commands/${scannerId}/stop`
    const ok = mqttClient?.publish(topic, JSON.stringify({}), { qos: 1 })
    if (ok) logger.debug('Sent stop command to', scannerId)
    return !!ok
  }

  function sendBandsCommand(scannerId, bands) {
    const topic = `${TOPIC_PREFIX}/commands/${scannerId}/bands`
    const payload = bands.map(b => ({
      name: b.name,
      start_hz: b.start_hz,
      stop_hz: b.stop_hz,
      enabled: b.enabled,
    }))
    const ok = mqttClient?.publish(topic, JSON.stringify(payload), { qos: 1 })
    if (ok) logger.debug('Sent bands command to', scannerId, payload)
    return !!ok
  }

  function sendGainCommand(scannerId, rxGain, rxGainMode) {
    const topic = `${TOPIC_PREFIX}/commands/${scannerId}/gain`
    const payload = { rx_gain: rxGain, rx_gain_mode: rxGainMode }
    const ok = mqttClient?.publish(topic, JSON.stringify(payload), { qos: 1 })
    if (ok) logger.debug('Sent gain command to', scannerId, payload)
    return !!ok
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

      // Add to timeline and cache for scrubber (so live scans are immediately available)
      const key = `${scannerId}:${data.band}`
      const timestamp = data.timestamp || new Date().toISOString()
      const timestampMs = new Date(timestamp).getTime()
      const scanId = `live-${timestampMs}` // Generate ID for live scans

      // Add to timeline if not already there
      if (!timelines.value[key]) {
        timelines.value[key] = []
      }
      const timelineEntry = { id: scanId, timestamp, band__name: data.band }
      const exists = timelines.value[key].some(t => t.timestamp === timestamp)
      if (!exists) {
        const updated = [...timelines.value[key], timelineEntry]
          .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
        const maxEntries = 10000
        timelines.value[key] = updated.length > maxEntries ? updated.slice(-maxEntries) : updated
      }

      // Add to decimated cache for scrubbing (used by findScanInDecimatedCache)
      if (!decimatedCache.value[key]) {
        decimatedCache.value[key] = []
      }
      const cacheExists = decimatedCache.value[key].some(s => s.timestamp === timestampMs)
      if (!cacheExists) {
        const cacheEntry = {
          timestamp: timestampMs,
          scan: {
            hz_lo: data.hz_lo,
            hz_hi: data.hz_hi,
            step: data.step,
            power: data.power,
            timestamp: timestamp,
          }
        }
        decimatedCache.value[key] = [...decimatedCache.value[key], cacheEntry]
          .sort((a, b) => a.timestamp - b.timestamp)
        // Limit cache size
        const maxCacheEntries = 200
        if (decimatedCache.value[key].length > maxCacheEntries) {
          decimatedCache.value[key] = decimatedCache.value[key].slice(-maxCacheEntries)
        }
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
    logger.debug('handleConfig:', scannerId, 'bands:', data.bands)
    const existing = scanners.value[scannerId] || {}
    scanners.value[scannerId] = {
      ...existing,
      id: scannerId,
      scanner_type: data.type || existing.scanner_type || 'unknown',
      // Identity (name/location/description) is owned by the server model and
      // arrives via REST — the MQTT config message no longer carries it. Preserve
      // what REST loaded; only fall back to the UUID for a never-before-seen unit.
      name: existing.name || scannerId,
      location: existing.location || '',
      description: existing.description || '',
      // asset_tag is device-reported (optional) and rides the config message;
      // metadata is server-owned and only arrives via REST, so preserve it.
      asset_tag: data.asset_tag ?? existing.asset_tag ?? '',
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
      logger.error(`Error loading cache for ${scannerId}/${bandName}:`, err)
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
      logger.error(`Error loading decimated cache for ${scannerId}/${bandName}:`, err)
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

  async function fetchGroups() {
    try {
      const response = await fetch('/api/groups/', {
        credentials: 'include',
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      groups.value = await response.json()
    } catch (error) {
      logger.error('Failed to fetch groups:', error)
    }
  }

  async function fetchGroup(id) {
    try {
      const response = await fetch(`/api/groups/${id}/`, {
        credentials: 'include',
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      return await response.json()
    } catch (error) {
      logger.error('Failed to fetch group:', error)
      return null
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
      logger.error('Failed to fetch scanners:', error)
    }
  }

  async function fetchMonitoredFrequencies(scannerId) {
    try {
      const response = await fetch(`/api/scanners/${scannerId}/monitored_frequencies/`, {
        credentials: 'include',
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const data = await response.json()
      monitoredFreqs.value = { ...monitoredFreqs.value, [scannerId]: data }
    } catch (error) {
      logger.error('Failed to fetch monitored frequencies:', error)
    }
  }

  function getMonitoredFrequencies(scannerId) {
    return monitoredFreqs.value[scannerId] || []
  }

  function getCsrfToken() {
    for (let c of document.cookie.split(';')) {
      c = c.trim()
      if (c.startsWith('csrftoken=')) return c.substring('csrftoken='.length)
    }
    return null
  }

  async function _mfRequest(url, method, body) {
    const csrf = getCsrfToken()
    const headers = { 'Content-Type': 'application/json' }
    if (csrf) headers['X-CSRFToken'] = csrf
    const res = await fetch(url, {
      method,
      headers,
      credentials: 'include',
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.status === 204 ? null : res.json()
  }

  // Category labels for the editor combobox (predefined + any in use, e.g. a
  // custom "Public Safety" already in the DB). Single source: the API.
  const monitoredCategories = ref([])
  async function fetchMonitoredCategories() {
    try {
      const res = await fetch('/api/monitored-frequencies/categories/', { credentials: 'include' })
      if (res.ok) monitoredCategories.value = await res.json()
    } catch (error) {
      logger.error('Failed to fetch categories:', error)
    }
  }
  function getMonitoredCategories() {
    return monitoredCategories.value
  }

  // Monitored-frequency CRUD. Server enforces permissions (staff / rw on the
  // scanner); the scanner scope is applied server-side from `scannerId`.
  async function createMonitoredFrequency(scannerId, data) {
    const result = await _mfRequest('/api/monitored-frequencies/', 'POST', { ...data, scanner: scannerId })
    await Promise.all([fetchMonitoredFrequencies(scannerId), fetchMonitoredCategories()])
    return result
  }

  async function updateMonitoredFrequency(scannerId, id, data) {
    const result = await _mfRequest(`/api/monitored-frequencies/${id}/`, 'PATCH', data)
    await Promise.all([fetchMonitoredFrequencies(scannerId), fetchMonitoredCategories()])
    return result
  }

  async function deleteMonitoredFrequency(scannerId, id) {
    await _mfRequest(`/api/monitored-frequencies/${id}/`, 'DELETE')
    await fetchMonitoredFrequencies(scannerId)
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
      logger.warn('No scan data for', scannerId, bandName)
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
    logger.debug('Exported:', filename)
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
      logger.error('Failed to fetch timeline:', error)
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
      logger.error('Failed to fetch history:', error)
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
      logger.error('Failed to fetch scan at time:', error)
      setApiError(`Scan: ${error.message}`)
      return null
    }
  }

  function soloBand(scannerId, bandName) {
    const scanner = scanners.value[scannerId]
    if (!scanner?.bands) return
    const bands = scanner.bands.map(b => ({ ...b, enabled: b.name === bandName }))
    sendBandsCommand(scannerId, bands)
  }

  function unsoloBand(scannerId) {
    const scanner = scanners.value[scannerId]
    if (!scanner?.bands) return
    const bands = scanner.bands.map(b => ({ ...b, enabled: true }))
    sendBandsCommand(scannerId, bands)
  }

  function isSoloed(scannerId, bandName) {
    const scanner = scanners.value[scannerId]
    if (!scanner?.bands || scanner.bands.length <= 1) return false
    const enabledBands = scanner.bands.filter(b => b.enabled)
    return enabledBands.length === 1 && enabledBands[0].name === bandName
  }

  return {
    scanners,
    scannerList,
    groups,
    monitoredFreqs,
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
    fetchMonitoredFrequencies,
    getMonitoredFrequencies,
    fetchMonitoredCategories,
    getMonitoredCategories,
    createMonitoredFrequency,
    updateMonitoredFrequency,
    deleteMonitoredFrequency,
    fetchGroups,
    fetchGroup,
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
    // Scanner commands
    sendStartCommand,
    sendStopCommand,
    sendBandsCommand,
    sendGainCommand,
    // Solo band
    soloBand,
    unsoloBand,
    isSoloed,
  }
})
