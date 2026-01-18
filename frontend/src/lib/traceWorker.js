/**
 * Web Worker for trace calculations (peak hold, averaging)
 * Offloads heavy array processing from main thread
 */

// Store trace history per trace ID
const traceHistory = {}
const MAX_HISTORY_SAMPLES = 30

/**
 * Update trace history and calculate peak/average
 * @param {string} traceId - Unique trace identifier
 * @param {number[]} power - Current power readings
 * @returns {Object} { peak, avg }
 */
function updateTrace(traceId, power) {
  if (!traceHistory[traceId]) {
    traceHistory[traceId] = {
      samples: [],
      peak: new Float32Array(power.length),
      avg: new Float32Array(power.length),
    }
    // Initialize peak with very low values
    traceHistory[traceId].peak.fill(-200)
  }

  const history = traceHistory[traceId]
  const len = power.length

  // Resize arrays if needed (band config changed)
  if (history.peak.length !== len) {
    history.peak = new Float32Array(len)
    history.peak.fill(-200)
    history.avg = new Float32Array(len)
    history.samples = []
  }

  // Update peak (max hold) - in place
  for (let i = 0; i < len; i++) {
    if (power[i] > history.peak[i]) {
      history.peak[i] = power[i]
    }
  }

  // Add sample to history (use typed array for efficiency)
  history.samples.push(Float32Array.from(power))
  if (history.samples.length > MAX_HISTORY_SAMPLES) {
    history.samples.shift()
  }

  // Calculate running average
  const sampleCount = history.samples.length
  history.avg.fill(0)
  for (const sample of history.samples) {
    for (let i = 0; i < len; i++) {
      history.avg[i] += sample[i]
    }
  }
  for (let i = 0; i < len; i++) {
    history.avg[i] /= sampleCount
  }

  // Return copies (transferable would be faster but more complex)
  return {
    peak: Array.from(history.peak),
    avg: Array.from(history.avg),
  }
}

/**
 * Reset peak hold for a trace
 * @param {string} traceId - Unique trace identifier
 */
function resetPeak(traceId) {
  if (traceHistory[traceId]) {
    traceHistory[traceId].peak.fill(-200)
  }
}

/**
 * Clear all history for a trace
 * @param {string} traceId - Unique trace identifier
 */
function clearTrace(traceId) {
  delete traceHistory[traceId]
}

// Handle messages from main thread
self.onmessage = function(e) {
  const { type, traceId, power } = e.data

  switch (type) {
    case 'update': {
      const result = updateTrace(traceId, power)
      self.postMessage({ type: 'result', traceId, ...result })
      break
    }
    case 'resetPeak': {
      resetPeak(traceId)
      self.postMessage({ type: 'peakReset', traceId })
      break
    }
    case 'clear': {
      clearTrace(traceId)
      self.postMessage({ type: 'cleared', traceId })
      break
    }
  }
}
