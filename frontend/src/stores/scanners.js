import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useScannersStore = defineStore('scanners', () => {
  const scanners = ref({})
  const latestScans = ref({})       // { scannerId: lastScan }
  const bandScans = ref({})         // { scannerId: { bandName: lastScan } }
  const connected = ref(false)
  const subscriptions = ref(new Set()) // Track subscribed scanner IDs
  let ws = null
  let reconnectTimeout = null

  const scannerList = computed(() => Object.values(scanners.value))

  function connect() {
    // Prevent multiple connections
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/scans/`
    console.log('Connecting to WebSocket:', wsUrl)

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      console.log('WebSocket connected')
      connected.value = true

      // Re-subscribe to any scanners we were tracking
      subscriptions.value.forEach(scannerId => {
        sendSubscribe(scannerId)
      })
    }

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data)

      if (message.type === 'connected') {
        console.log('WS confirmed:', message)
      } else if (message.type === 'scan') {
        handleScan(message.data)
      } else if (message.type === 'status') {
        handleStatus(message.data)
      } else if (message.type === 'config') {
        handleConfig(message.data)
      } else if (message.type === 'subscribed') {
        console.log('Subscribed to scanner:', message.scanner_id)
      } else if (message.type === 'unsubscribed') {
        console.log('Unsubscribed from scanner:', message.scanner_id)
      }
    }

    ws.onclose = () => {
      console.log('WebSocket disconnected')
      connected.value = false
      ws = null

      // Reconnect after 2 seconds
      if (reconnectTimeout) clearTimeout(reconnectTimeout)
      reconnectTimeout = setTimeout(connect, 2000)
    }

    ws.onerror = (error) => {
      console.error('WebSocket error:', error)
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

  function sendSubscribe(scannerId) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'subscribe', scanner_id: scannerId }))
    }
  }

  function sendUnsubscribe(scannerId) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'unsubscribe', scanner_id: scannerId }))
    }
  }

  // Subscribe to a specific scanner's data
  function subscribe(scannerId) {
    if (!scannerId) return

    subscriptions.value.add(scannerId)
    sendSubscribe(scannerId)
    console.log('Subscribe requested:', scannerId)
  }

  // Unsubscribe from a specific scanner's data
  function unsubscribe(scannerId) {
    if (!scannerId) return

    subscriptions.value.delete(scannerId)
    sendUnsubscribe(scannerId)
    console.log('Unsubscribe requested:', scannerId)
  }

  function handleScan(data) {
    const scannerId = data.scanner_id

    if (scannerId) {
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

      // Store latest scan (without scanner_id in the scan data)
      const { scanner_id, ...scanData } = data
      latestScans.value[scannerId] = scanData

      // Also store by band name if available
      if (data.band) {
        console.log('handleScan: storing band scan for', scannerId, data.band)
        if (!bandScans.value[scannerId]) {
          bandScans.value[scannerId] = {}
        }
        bandScans.value[scannerId][data.band] = scanData

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
          console.log('Auto-added band:', data.band)
        }
      } else {
        console.log('handleScan: no band name in scan data', data)
      }
    }
  }

  function handleStatus(data) {
    const scannerId = data.scanner_id

    if (scannerId) {
      if (!scanners.value[scannerId]) {
        scanners.value[scannerId] = { id: scannerId, name: scannerId }
      }
      scanners.value[scannerId] = {
        ...scanners.value[scannerId],
        ...data,
      }
    }
  }

  function handleConfig(data) {
    const scannerId = data.scanner_id || data.id

    if (scannerId) {
      console.log('handleConfig:', scannerId, 'bands:', data.bands)
      scanners.value[scannerId] = {
        ...scanners.value[scannerId],
        id: scannerId,
        name: data.name || scannerId,
        type: data.type || 'unknown',
        location: data.location || '',
        description: data.description || '',
        bands: data.bands || [],
        settings: data.settings || {},
        online: true,
      }
    }
  }

  async function fetchScanners() {
    try {
      const response = await fetch('/api/scanners/')
      const data = await response.json()
      data.forEach(scanner => {
        scanners.value[scanner.id] = scanner
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

  return {
    scanners,
    scannerList,
    latestScans,
    bandScans,
    connected,
    connect,
    disconnect,
    subscribe,
    unsubscribe,
    fetchScanners,
    exportScanCSV,
  }
})
