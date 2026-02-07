/**
 * Scan History API abstraction
 * Works with Django backend and Go :8080 server (including Wails desktop)
 */
import { logger } from './logger.js'

// Detect Wails desktop app - use localhost:8080 for API
const isWails = !!(window.wails || window.go)

// API base URL - in Wails mode, always use localhost:8080
const API_BASE = isWails ? 'http://localhost:8080' : (import.meta.env.VITE_API_BASE || '')

/**
 * Fetch timeline entries for a band
 * @param {string} band - Band name
 * @param {number} hours - Hours of history to fetch
 * @returns {Promise<Array>} Timeline entries [{id, timestamp, band__name}, ...]
 */
export async function fetchTimeline(band, hours = 24) {
  try {
    const res = await fetch(`${API_BASE}/api/scans/timeline?band=${encodeURIComponent(band)}&hours=${hours}`)
    if (!res.ok) {
      logger.error('Failed to fetch timeline:', res.status)
      return []
    }
    const entries = await res.json()

    // Normalize format: Go returns {band}, Django expects {band__name}
    return entries.map(e => ({
      ...e,
      band__name: e.band__name || e.band,
    }))
  } catch (err) {
    logger.error('Failed to fetch timeline:', err)
    return []
  }
}

/**
 * Fetch scan at a specific time
 * @param {string} band - Band name
 * @param {Date|string} time - Time to fetch scan for
 * @returns {Promise<Object|null>} Scan data or null
 */
export async function fetchScanAtTime(band, time) {
  const timeStr = time instanceof Date ? time.toISOString() : time

  try {
    const res = await fetch(`${API_BASE}/api/scans/at-time?band=${encodeURIComponent(band)}&time=${encodeURIComponent(timeStr)}`)
    if (!res.ok) {
      if (res.status === 404) return null
      logger.error('Failed to fetch scan at time:', res.status)
      return null
    }
    return res.json()
  } catch (err) {
    logger.error('Failed to fetch scan at time:', err)
    return null
  }
}

/**
 * Fetch decimated scans for scrubber preview
 * @param {string} band - Band name
 * @param {number} hours - Hours of history
 * @returns {Promise<Array>} Decimated scans for fast preview
 */
export async function fetchDecimatedScans(band, hours = 6) {
  try {
    const res = await fetch(`${API_BASE}/api/scans/decimated?band=${encodeURIComponent(band)}&hours=${hours}`)
    if (!res.ok) {
      logger.error('Failed to fetch decimated scans:', res.status)
      return []
    }
    return res.json()
  } catch (err) {
    logger.error('Failed to fetch decimated scans:', err)
    return []
  }
}

/**
 * Get scan database statistics
 * @returns {Promise<Object>} Stats object
 */
export async function fetchScanStats() {
  try {
    const res = await fetch(`${API_BASE}/api/scans/stats`)
    if (!res.ok) {
      logger.error('Failed to fetch scan stats:', res.status)
      return {}
    }
    return res.json()
  } catch (err) {
    logger.error('Failed to fetch scan stats:', err)
    return {}
  }
}

/**
 * Check if scan history is available
 * @returns {boolean} True if scan history API is available
 */
export function isScanHistoryAvailable() {
  // Available in both browser and Wails mode via HTTP API
  return true
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
