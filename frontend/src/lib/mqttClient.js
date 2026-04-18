import mqtt from 'mqtt'
import { logger } from './logger.js'

export const TOPIC_PREFIX = 'spectrum'

function getMqttUrl() {
  const host = window.location.hostname
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const port = window.location.port
  const portPart = port ? `:${port}` : ''
  return `${protocol}//${host}${portPart}/mqtt`
}

async function fetchMqttCredentials() {
  try {
    const response = await fetch('/api/mqtt/credentials/', {
      credentials: 'include',
    })
    if (!response.ok) throw new Error('Failed to fetch MQTT credentials')
    return await response.json()
  } catch (error) {
    logger.error('Failed to fetch MQTT credentials:', error)
    return null
  }
}

export class MqttClient {
  constructor() {
    this._client = null
    this._connecting = false
    this._subscriptions = new Set()
    this._messageCallback = null
    this._stateCallback = null
    this._errorCallback = null
    this._visibilityHandler = null
    this._beforeUnloadHandler = null
    this._disconnectTimer = null
  }

  get connected() {
    return !!(this._client && this._client.connected)
  }

  get subscriptions() {
    return this._subscriptions
  }

  async connect() {
    // Already has an active client (connected or reconnecting)
    if (this._client || this._connecting) return

    this._connecting = true
    try {
      const credentials = await fetchMqttCredentials()
      if (!credentials) {
        logger.error('Could not get MQTT credentials')
        return
      }

      const mqttUrl = getMqttUrl()
      logger.info('MQTT connecting to:', mqttUrl, 'as', credentials.username)

      this._client = mqtt.connect(mqttUrl, {
        clientId: `spectrum-frontend-${Math.random().toString(16).substring(2, 10)}`,
        username: credentials.username,
        password: credentials.password,
        clean: true,
        keepalive: 15,
        reconnectPeriod: 2000,
        connectTimeout: 5000,
      })

      this._setupEvents()
      this._setupVisibility()
      this._setupBeforeUnload()
    } catch (error) {
      logger.error('MQTT connect failed:', error)
      this._client = null
    } finally {
      this._connecting = false
    }
  }

  disconnect() {
    this._connecting = false
    if (this._disconnectTimer) {
      clearTimeout(this._disconnectTimer)
      this._disconnectTimer = null
    }
    if (this._visibilityHandler) {
      document.removeEventListener('visibilitychange', this._visibilityHandler)
      this._visibilityHandler = null
    }
    if (this._beforeUnloadHandler) {
      window.removeEventListener('beforeunload', this._beforeUnloadHandler)
      this._beforeUnloadHandler = null
    }
    if (this._client) {
      this._client.removeAllListeners()
      this._client.end(true)
      this._client = null
    }
    this._subscriptions.clear()
    this._stateCallback?.(false)
  }

  subscribe(scannerId) {
    if (!scannerId) return
    if (this._subscriptions.has(scannerId)) return
    this._subscriptions.add(scannerId)
    this._subscribeTopics(scannerId)
  }

  unsubscribe(scannerId) {
    if (!scannerId) return
    if (!this._subscriptions.has(scannerId)) return
    this._subscriptions.delete(scannerId)
    this._unsubscribeTopics(scannerId)
  }

  publish(topic, payload, opts) {
    if (!this.connected) {
      logger.warn('MQTT not connected')
      return false
    }
    this._client.publish(topic, payload, opts)
    return true
  }

  onMessage(callback) {
    this._messageCallback = callback
  }

  onStateChange(callback) {
    this._stateCallback = callback
  }

  onError(callback) {
    this._errorCallback = callback
  }

  _setupEvents() {
    const client = this._client

    client.on('connect', () => {
      logger.info('MQTT connected')
      // Cancel any pending "disconnected" notification
      clearTimeout(this._disconnectTimer)
      this._disconnectTimer = null
      this._stateCallback?.(true)

      for (const scannerId of this._subscriptions) {
        this._subscribeTopics(scannerId)
      }
      if (this._subscriptions.size > 0) {
        logger.debug(`Re-subscribed to ${this._subscriptions.size} scanners`)
      }
    })

    client.on('message', (topic, payload) => {
      this._messageCallback?.(topic, payload)
    })

    client.on('close', () => {
      logger.debug('MQTT connection closed')
      // Debounce: only report disconnected if we stay down for 5s.
      // Avoids flapping during normal reconnect cycles.
      clearTimeout(this._disconnectTimer)
      this._disconnectTimer = setTimeout(() => {
        if (!this.connected) {
          this._stateCallback?.(false)
        }
      }, 5000)
    })

    client.on('error', (error) => {
      logger.error('MQTT error:', error.message || error)
      this._errorCallback?.(error)
    })

    client.on('reconnect', () => {
      logger.debug('MQTT reconnecting...')
    })

    client.on('offline', () => {
      logger.debug('MQTT offline')
    })
  }

  _setupVisibility() {
    this._visibilityHandler = () => {
      if (document.visibilityState === 'visible' && this._client && !this._client.connected) {
        logger.debug('Page visible — forcing MQTT reconnect')
        this._client.reconnect()
      }
    }
    document.addEventListener('visibilitychange', this._visibilityHandler)
  }

  _setupBeforeUnload() {
    this._beforeUnloadHandler = () => {
      if (this._client) {
        this._client.end(true)
      }
    }
    window.addEventListener('beforeunload', this._beforeUnloadHandler)
  }

  _subscribeTopics(scannerId) {
    if (!this.connected) return
    this._client.subscribe(`${TOPIC_PREFIX}/scanners/${scannerId}/config`, { qos: 1 })
    this._client.subscribe(`${TOPIC_PREFIX}/scanners/${scannerId}/status`, { qos: 1 })
    this._client.subscribe(`${TOPIC_PREFIX}/scanners/${scannerId}/scan`, { qos: 0 })
    this._client.subscribe(`${TOPIC_PREFIX}/scanners/${scannerId}/timeline`, { qos: 0 })
  }

  _unsubscribeTopics(scannerId) {
    if (!this.connected) return
    this._client.unsubscribe(`${TOPIC_PREFIX}/scanners/${scannerId}/config`)
    this._client.unsubscribe(`${TOPIC_PREFIX}/scanners/${scannerId}/status`)
    this._client.unsubscribe(`${TOPIC_PREFIX}/scanners/${scannerId}/scan`)
    this._client.unsubscribe(`${TOPIC_PREFIX}/scanners/${scannerId}/timeline`)
  }
}
