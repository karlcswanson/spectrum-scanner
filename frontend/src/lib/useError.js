/**
 * Shared error handling composable
 * Provides consistent error tracking across all frontends
 */
import { ref, computed } from 'vue'

/**
 * Create an error handler with auto-expiring error messages
 * @param {number} displayDurationMs - How long errors stay visible (default: 10000ms)
 * @returns {Object} Error handling utilities
 */
export function useError(displayDurationMs = 10000) {
  const lastError = ref(null) // { message: string, timestamp: number }
  const now = ref(Date.now())
  let nowInterval = null

  /**
   * Whether an error should currently be displayed
   */
  const showError = computed(() => {
    return lastError.value && (now.value - lastError.value.timestamp) < displayDurationMs
  })

  /**
   * Set an error message
   * @param {string} message - Error message to display
   */
  function setError(message) {
    lastError.value = { message, timestamp: Date.now() }
  }

  /**
   * Clear the current error
   */
  function clearError() {
    lastError.value = null
  }

  /**
   * Wrap an async operation with error handling
   * @param {Function} fn - Async function to execute
   * @param {string} context - Context for error message (e.g., "Connect", "Start")
   * @returns {Promise<any>} Result of the function or undefined on error
   */
  async function withErrorHandling(fn, context) {
    try {
      return await fn()
    } catch (err) {
      const message = err?.message || String(err)
      setError(`${context}: ${message}`)
      console.error(`${context} failed:`, err)
      return undefined
    }
  }

  /**
   * Start the timer for error display (call on mount)
   */
  function startTimer() {
    if (!nowInterval) {
      nowInterval = setInterval(() => {
        now.value = Date.now()
      }, 1000)
    }
  }

  /**
   * Stop the timer (call on unmount)
   */
  function stopTimer() {
    if (nowInterval) {
      clearInterval(nowInterval)
      nowInterval = null
    }
  }

  return {
    lastError,
    showError,
    setError,
    clearError,
    withErrorHandling,
    startTimer,
    stopTimer,
  }
}
