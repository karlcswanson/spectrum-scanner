/**
 * Shared scan data management composable
 * Handles scan data storage and event bus signaling for all frontends
 *
 * Uses non-reactive storage for performance (scan data can be large and updates frequently)
 * Uses VueUse event bus for redraw signals
 * Pre-decimates data for display while keeping full resolution for export
 */
import { ref } from 'vue'
import { useEventBus } from '@vueuse/core'

// Event bus for scan redraw signals (same key = same singleton across app)
export const scanBus = useEventBus('scan-redraw')

// Target points for decimated display (roughly 1080p width)
const DISPLAY_POINTS = 1920

/**
 * Decimate power array using max-pooling to preserve peaks
 * @param {number[]} power - Full resolution power array
 * @param {number} targetPoints - Target number of points
 * @returns {number[]} Decimated power array
 */
function decimatePower(power, targetPoints = DISPLAY_POINTS) {
  if (!power || power.length <= targetPoints) {
    return power
  }

  const factor = power.length / targetPoints
  const result = new Array(targetPoints)

  for (let i = 0; i < targetPoints; i++) {
    const start = Math.floor(i * factor)
    const end = Math.floor((i + 1) * factor)
    // Use max value in each bin to preserve peaks
    let max = power[start]
    for (let j = start + 1; j < end && j < power.length; j++) {
      if (power[j] > max) max = power[j]
    }
    result[i] = max
  }

  return result
}

/**
 * Create scan data manager
 * @returns {Object} Scan data management utilities
 */
export function useScanData() {
  // Scan data stored in plain object (NOT reactive) for performance
  // Each entry has: { hz_lo, hz_hi, step, power (decimated), powerFull, timestamp }
  const scanDataRaw = {}

  // Lightweight reactive counter - triggers template re-render for scan info text
  const scanUpdateCount = ref(0)

  /**
   * Handle incoming scan data
   * @param {Object} data - Scan data { band, hz_lo, hz_hi, step, power, timestamp }
   */
  function handleScanData(data) {
    if (!data.band || !data.power) return

    const fullPower = data.power
    const decimatedPower = decimatePower(fullPower)

    // Store both full and decimated data
    scanDataRaw[data.band] = {
      hz_lo: data.hz_lo,
      hz_hi: data.hz_hi,
      step: data.step,
      power: decimatedPower,      // Decimated for display
      powerFull: fullPower,       // Full resolution for export
      pointsFull: fullPower.length,
      timestamp: data.timestamp,
    }

    // Signal the chart to redraw (just the band name, not data)
    scanBus.emit(data.band)

    // Bump counter to trigger template re-render for scan info text
    scanUpdateCount.value++
  }

  /**
   * Get scan data for a band (called by chart component)
   * Returns decimated power for display performance
   * @param {string} bandName - Name of the band
   * @returns {Object|null} Scan data or null if not available
   */
  function getScanData(bandName) {
    return scanDataRaw[bandName] || null
  }

  /**
   * Get full resolution scan data for a band (for export)
   * @param {string} bandName - Name of the band
   * @returns {Object|null} Scan data with full power array or null
   */
  function getFullScanData(bandName) {
    const scan = scanDataRaw[bandName]
    if (!scan) return null
    return {
      ...scan,
      power: scan.powerFull,  // Replace decimated with full
    }
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
   * Format step size for display (kHz or Hz)
   * @param {number} stepHz - Step size in Hz
   * @returns {string} Formatted step size
   */
  function formatStep(stepHz) {
    if (stepHz >= 1000) {
      return `${(stepHz / 1000).toFixed(1)} kHz`
    }
    return `${stepHz.toFixed(0)} Hz`
  }

  /**
   * Get scan info string for display (e.g., "5765 pts | 12.5 kHz | -95.2 to -42.1 dBm")
   * Uses full resolution data for accurate stats
   * @param {string} bandName - Name of the band
   * @returns {string} Formatted scan info or '--' if no data
   */
  function getScanInfo(bandName) {
    const scan = scanDataRaw[bandName]
    if (!scan?.powerFull) return '--'
    const power = scan.powerFull
    const points = power.length
    const step = formatStep(scan.step)

    // Find min/max efficiently
    let minP = power[0]
    let maxP = power[0]
    for (let i = 1; i < power.length; i++) {
      if (power[i] < minP) minP = power[i]
      if (power[i] > maxP) maxP = power[i]
    }

    return `${points} pts | ${step} | ${minP.toFixed(1)} to ${maxP.toFixed(1)} dBm`
  }

  /**
   * Generate CSV content from full resolution scan data
   * @param {string} bandName - Name of the band
   * @returns {string|null} CSV content or null if no data
   */
  function generateCSV(bandName) {
    const scan = scanDataRaw[bandName]
    if (!scan?.powerFull) return null

    const power = scan.powerFull
    let csv = 'Frequency (MHz),Power (dBm)\n'
    const startMHz = scan.hz_lo / 1e6
    const stepMHz = scan.step / 1e6

    for (let i = 0; i < power.length; i++) {
      const freq = startMHz + (i * stepMHz)
      csv += `${freq.toFixed(6)},${power[i].toFixed(2)}\n`
    }
    return csv
  }

  /**
   * Download scan data as CSV file (full resolution)
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
    getFullScanData,
    clearScanData,
    getScanInfo,
    generateCSV,
    downloadCSV,
  }
}
