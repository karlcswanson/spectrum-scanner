import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { logger } from '@lib'

// Get CSRF token from cookie
function getCsrfToken() {
  const name = 'csrftoken'
  const cookies = document.cookie.split(';')
  for (let cookie of cookies) {
    cookie = cookie.trim()
    if (cookie.startsWith(name + '=')) {
      return cookie.substring(name.length + 1)
    }
  }
  return null
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const loading = ref(true)
  const error = ref(null)

  const isAuthenticated = computed(() => !!user.value)
  const isStaff = computed(() => user.value?.is_staff || false)
  const isReadonly = computed(() => user.value?.readonly || false)
  const shareLabel = computed(() => user.value?.share_label || null)

  async function checkAuth() {
    loading.value = true
    error.value = null
    try {
      const response = await fetch('/api/auth/user/', {
        credentials: 'include',
      })
      const data = await response.json()
      if (data.id) {
        user.value = data
      } else {
        user.value = null
      }
    } catch (err) {
      logger.error('Auth check failed:', err)
      user.value = null
    } finally {
      loading.value = false
    }
  }

  async function login(username, password) {
    loading.value = true
    error.value = null
    try {
      const csrfToken = getCsrfToken()
      const headers = {
        'Content-Type': 'application/json',
      }
      if (csrfToken) {
        headers['X-CSRFToken'] = csrfToken
      }

      const response = await fetch('/api/auth/login/', {
        method: 'POST',
        headers,
        credentials: 'include',
        body: JSON.stringify({ username, password }),
      })

      const data = await response.json()

      if (response.ok) {
        user.value = data
        return true
      } else {
        error.value = data.error || 'Login failed'
        return false
      }
    } catch (err) {
      logger.error('Login failed:', err)
      error.value = 'Network error'
      return false
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    try {
      const csrfToken = getCsrfToken()
      const headers = {}
      if (csrfToken) {
        headers['X-CSRFToken'] = csrfToken
      }

      await fetch('/api/auth/logout/', {
        method: 'POST',
        headers,
        credentials: 'include',
      })
    } catch (err) {
      logger.error('Logout failed:', err)
    }
    user.value = null
  }

  return {
    user,
    loading,
    error,
    isAuthenticated,
    isStaff,
    isReadonly,
    shareLabel,
    checkAuth,
    login,
    logout,
  }
})
