/**
 * Frequency conversion and formatting utilities
 * Shared across all frontends (Spectrum Server, Standalone, Desktop)
 */

/**
 * Convert Hz to MHz
 * @param {number} hz - Frequency in Hz
 * @returns {number} Frequency in MHz
 */
export function hzToMHz(hz) {
  return hz / 1e6
}

/**
 * Convert MHz to Hz
 * @param {number} mhz - Frequency in MHz
 * @returns {number} Frequency in Hz
 */
export function mhzToHz(mhz) {
  return mhz * 1e6
}

/**
 * Format a frequency range as "start-stop MHz"
 * @param {number} startHz - Start frequency in Hz
 * @param {number} stopHz - Stop frequency in Hz
 * @returns {string} Formatted range string
 */
export function formatFreqRange(startHz, stopHz) {
  const startMHz = (startHz / 1e6).toFixed(0)
  const stopMHz = (stopHz / 1e6).toFixed(0)
  return `${startMHz}-${stopMHz} MHz`
}

/**
 * Format a single frequency with appropriate precision
 * @param {number} hz - Frequency in Hz
 * @param {number} decimals - Number of decimal places (default: 3)
 * @returns {string} Formatted frequency string with MHz suffix
 */
export function formatFreq(hz, decimals = 3) {
  return `${(hz / 1e6).toFixed(decimals)} MHz`
}

/**
 * Calculate step size in Hz from scan data
 * @param {number} hzLo - Low frequency in Hz
 * @param {number} hzHi - High frequency in Hz
 * @param {number} numPoints - Number of data points
 * @returns {number} Step size in Hz
 */
export function calculateStep(hzLo, hzHi, numPoints) {
  if (numPoints <= 1) return 0
  return (hzHi - hzLo) / (numPoints - 1)
}

/**
 * Get frequency at a specific index in scan data
 * @param {number} hzLo - Low frequency in Hz
 * @param {number} step - Step size in Hz
 * @param {number} index - Point index
 * @returns {number} Frequency in Hz at that index
 */
export function freqAtIndex(hzLo, step, index) {
  return hzLo + (index * step)
}
