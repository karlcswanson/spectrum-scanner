/**
 * Shared scan data management composable
 * Handles scan data storage and event bus signaling for all frontends
 *
 * Uses non-reactive storage for performance (scan data can be large and updates frequently)
 * Uses VueUse event bus for redraw signals
 */
import { ref } from 'vue'
import { useEventBus } from '@vueuse/core'

// Event bus for scan redraw signals (same key = same singleton across app)
export const scanBus = useEventBus('scan-redraw')

/**
 * Create scan data manager
 * @returns {Object} Scan data management utilities
 */
export function useScanData() {
  // Scan data stored in plain object (NOT reactive) for performance
  // Access via getScanData(bandName) or listen to scanBus
  const scanDataRaw = {}

  // Lightweight reactive counter - triggers template re-render for scan info text
  const scanUpdateCount = ref(0)

  /**
   * Handle incoming scan data
   * @param {Object} data - Scan data { band, hz_lo, hz_hi, step, power, timestamp }
   */
  function handleScanData(data) {
    if (!data.band || !data.power) return

    // Store directly in plain object (no Vue overhead)
    scanDataRaw[data.band] = {
      hz_lo: data.hz_lo,
      hz_hi: data.hz_hi,
      step: data.step,
      power: data.power,
      timestamp: data.timestamp,
    }

    // Signal the chart to redraw (just the band name, not data)
    scanBus.emit(data.band)

    // Bump counter to trigger template re-render for scan info text
    scanUpdateCount.value++
  }

  /**
   * Get scan data for a band (called by chart component)
   * @param {string} bandName - Name of the band
   * @returns {Object|null} Scan data or null if not available
   */
  function getScanData(bandName) {
    return scanDataRaw[bandName] || null
  }

  /**
   * Clear scan data for a band or all bands
   * @param {string} [bandName] - Band to clear (omit for all)
   */
  function clearScanData(bandName) {
    if (bandName) {
      delete scanDataRaw[bandName]
    } else {
      Object.keys(scanDataRaw).forEach(key => delete scanDataRaw[key])
    }
    scanUpdateCount.value++
  }

  /**
   * Get scan info string for display (e.g., "266 pts | -95.2 to -42.1 dBm")
   * @param {string} bandName - Name of the band
   * @returns {string} Formatted scan info or '--' if no data
   */
  function getScanInfo(bandName) {
    const scan = getScanData(bandName)
    if (!scan?.power) return '--'
    const points = scan.power.length
    const minP = Math.min(...scan.power).toFixed(1)
    const maxP = Math.max(...scan.power).toFixed(1)
    return `${points} pts | ${minP} to ${maxP} dBm`
  }

  /**
   * Generate CSV content from scan data
   * @param {string} bandName - Name of the band
   * @returns {string|null} CSV content or null if no data
   */
  function generateCSV(bandName) {
    const scan = getScanData(bandName)
    if (!scan) return null

    let csv = 'Frequency (MHz),Power (dBm)\n'
    const startMHz = scan.hz_lo / 1e6
    const stepMHz = scan.step / 1e6

    for (let i = 0; i < scan.power.length; i++) {
      const freq = startMHz + (i * stepMHz)
      csv += `${freq.toFixed(6)},${scan.power[i].toFixed(2)}\n`
    }
    return csv
  }

  /**
   * Download scan data as CSV file
   * @param {string} bandName - Name of the band
   * @param {string} [scannerName] - Optional scanner name for filename
   */
  function downloadCSV(bandName, scannerName = '') {
    const csv = generateCSV(bandName)
    if (!csv) return

    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const prefix = scannerName ? `${scannerName.replace(/\s+/g, '-')}_` : 'scan_'
    const filename = `${prefix}${bandName.replace(/\s+/g, '-')}_${timestamp}.csv`

    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  return {
    scanUpdateCount,
    handleScanData,
    getScanData,
    clearScanData,
    getScanInfo,
    generateCSV,
    downloadCSV,
  }
}
