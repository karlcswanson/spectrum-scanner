/**
 * Simple logger utility that can be disabled in production.
 * Debug logs are only shown in development mode.
 * Errors are always logged (but can be suppressed if needed).
 */

const isDev = import.meta.env.DEV

export const logger = {
  /**
   * Debug log - only shown in development
   */
  debug(...args) {
    if (isDev) {
      console.log('[DEBUG]', ...args)
    }
  },

  /**
   * Info log - only shown in development
   */
  info(...args) {
    if (isDev) {
      console.log('[INFO]', ...args)
    }
  },

  /**
   * Warning log - always shown
   */
  warn(...args) {
    console.warn('[WARN]', ...args)
  },

  /**
   * Error log - always shown
   */
  error(...args) {
    console.error('[ERROR]', ...args)
  },
}

export default logger
