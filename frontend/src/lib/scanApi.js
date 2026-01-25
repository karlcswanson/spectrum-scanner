/**
 * Scan History API abstraction
 * Works with Django backend, Go :8080 server, and Wails bindings
 */
import { logger } from './logger.js'

// API base URL (configurable via env)
const API_BASE = import.meta.env.VITE_API_BASE || ''

// Lazy check for Wails - window.go.main.App is injected after page load
function isWails() {
  return typeof window !== 'undefined' && !!window.go?.main?.App
}

/**
 * Fetch timeline entries for a band
 * @param {string} band - Band name
 * @param {number} hours - Hours of history to fetch
 * @returns {Promise<Array>} Timeline entries [{id, timestamp, band__name}, ...]
 */
export async function fetchTimeline(band, hours = 24) {
  let entries = []

  if (isWails()) {
    entries = await window.go.main.App.GetTimeline(band, hours)
    entries = entries || []
  } else {
    const res = await fetch(`${API_BASE}/api/scans/timeline?band=${encodeURIComponent(band)}&hours=${hours}`)
    if (!res.ok) {
      logger.error('Failed to fetch timeline:', res.status)
      return []
    }
    entries = await res.json()
  }

  // Normalize format: Go returns {band}, Django expects {band__name}
  return entries.map(e => ({
    ...e,
    band__name: e.band__name || e.band,
  }))
}

/**
 * Fetch scan at a specific time
 * @param {string} band - Band name
 * @param {Date|string} time - Time to fetch scan for
 * @returns {Promise<Object|null>} Scan data or null
 */
export async function fetchScanAtTime(band, time) {
  const timeStr = time instanceof Date ? time.toISOString() : time

  if (isWails()) {
    return window.go.main.App.GetScanAtTime(band, timeStr)
  }

  const res = await fetch(`${API_BASE}/api/scans/at-time?band=${encodeURIComponent(band)}&time=${encodeURIComponent(timeStr)}`)
  if (!res.ok) {
    if (res.status === 404) return null
    logger.error('Failed to fetch scan at time:', res.status)
    return null
  }
  return res.json()
}

/**
 * Fetch decimated scans for scrubber preview
 * @param {string} band - Band name
 * @param {number} hours - Hours of history
 * @returns {Promise<Array>} Decimated scans for fast preview
 */
export async function fetchDecimatedScans(band, hours = 6) {
  if (isWails()) {
    const scans = await window.go.main.App.GetDecimatedScans(band, hours)
    return scans || []
  }

  const res = await fetch(`${API_BASE}/api/scans/decimated?band=${encodeURIComponent(band)}&hours=${hours}`)
  if (!res.ok) {
    logger.error('Failed to fetch decimated scans:', res.status)
    return []
  }
  return res.json()
}

/**
 * Get scan database statistics
 * @returns {Promise<Object>} Stats object
 */
export async function fetchScanStats() {
  if (isWails()) {
    return window.go.main.App.GetScanStats()
  }

  const res = await fetch(`${API_BASE}/api/scans/stats`)
  if (!res.ok) {
    logger.error('Failed to fetch scan stats:', res.status)
    return {}
  }
  return res.json()
}

/**
 * Check if scan history is available
 * @returns {boolean} True if scan history API is available
 */
export function isScanHistoryAvailable() {
  // In Wails, always available (local SQLite)
  if (isWails()) return true
  // In browser, check if we have the API
  return true // Assume available, will fail gracefully if not
}

/**
 * Build a decimated cache from fetched scans
 * @param {Array} decimatedScans - Array of decimated scans
 * @returns {Map} Cache keyed by timestamp
 */
export function buildDecimatedCache(decimatedScans) {
  const cache = new Map()
  for (const scan of decimatedScans) {
    const ts = new Date(scan.timestamp).getTime()
    cache.set(ts, scan)
  }
  return cache
}

/**
 * Find closest scan in decimated cache
 * @param {Map} cache - Decimated cache
 * @param {Date} targetTime - Target time
 * @returns {Object|null} Closest scan or null
 */
export function findClosestInCache(cache, targetTime) {
  const targetTs = targetTime.getTime()
  let closest = null
  let minDiff = Infinity

  for (const [ts, scan] of cache) {
    const diff = Math.abs(ts - targetTs)
    if (diff < minDiff) {
      minDiff = diff
      closest = scan
    }
  }

  return closest
}
