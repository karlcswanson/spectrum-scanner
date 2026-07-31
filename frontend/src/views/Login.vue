<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const submitting = ref(false)
const csrfToken = ref('')

function getCookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)')
  return m ? m.pop() : ''
}

// Ensure auth.ssoEnabled is populated and the CSRF cookie is set (checkAuth hits
// /api/auth/user/, which sets it) before reading the token for the SSO form.
onMounted(async () => {
  if (auth.loading) await auth.checkAuth()
  csrfToken.value = getCookie('csrftoken')
})

async function handleSubmit() {
  if (submitting.value) return
  submitting.value = true

  const success = await auth.login(username.value, password.value)
  if (success) {
    router.push('/')
  }

  submitting.value = false
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-900">
    <div class="max-w-md w-full space-y-8 p-8">
      <div class="text-center">
        <img src="/logo.png" alt="Micboard" class="w-full mb-6" />
        <h2 class="text-3xl font-bold text-white">
          Spectrum Server
        </h2>
        <p class="mt-2 text-sm text-gray-400">
          Sign in to view spectrum data
        </p>
      </div>

      <!-- Enterprise SSO first (primary) when enabled. Full-page navigation —
           the OIDC flow is browser redirects to the identity provider. -->
      <div v-if="auth.ssoEnabled" class="mt-8">
        <!-- python-social-auth's login view is POST-only, so submit a form
             (with the CSRF token) rather than a link. -->
        <form method="post" :action="auth.ssoLoginUrl">
          <input type="hidden" name="csrfmiddlewaretoken" :value="csrfToken" />
          <button
            type="submit"
            class="w-full flex items-center justify-center gap-2 py-2 px-4 rounded-md shadow-sm text-sm font-medium focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
            :class="auth.ssoBrand === 'microsoft'
              ? 'bg-white text-gray-700 border border-gray-400 hover:bg-gray-100'
              : 'bg-blue-600 text-white hover:bg-blue-700'"
          >
            <svg v-if="auth.ssoBrand === 'microsoft'" width="18" height="18" viewBox="0 0 21 21" aria-hidden="true">
              <rect x="1" y="1" width="9" height="9" fill="#f25022" />
              <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
              <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
              <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
            </svg>
            <span>{{ auth.ssoLabel }}</span>
          </button>
        </form>
        <div class="relative mt-6">
          <div class="absolute inset-0 flex items-center">
            <div class="w-full border-t border-gray-700"></div>
          </div>
          <div class="relative flex justify-center text-sm">
            <span class="px-2 bg-gray-900 text-gray-500">or use a local account</span>
          </div>
        </div>
      </div>

      <form :class="[auth.ssoEnabled ? 'mt-6' : 'mt-8', 'space-y-6']" @submit.prevent="handleSubmit">
        <div v-if="auth.error" class="bg-red-900/50 border border-red-500 text-red-200 px-4 py-3 rounded">
          {{ auth.error }}
        </div>

        <div class="space-y-4">
          <div>
            <label for="username" class="block text-sm font-medium text-gray-300">
              Username
            </label>
            <input
              id="username"
              v-model="username"
              type="text"
              required
              autocomplete="username"
              class="mt-1 block w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="Enter your username"
            />
          </div>

          <div>
            <label for="password" class="block text-sm font-medium text-gray-300">
              Password
            </label>
            <input
              id="password"
              v-model="password"
              type="password"
              required
              autocomplete="current-password"
              class="mt-1 block w-full px-3 py-2 bg-gray-800 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="Enter your password"
            />
          </div>
        </div>

        <button
          type="submit"
          :disabled="submitting"
          class="w-full flex justify-center py-2 px-4 rounded-md shadow-sm text-sm font-medium focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
          :class="auth.ssoEnabled
            ? 'border border-gray-600 text-gray-200 bg-gray-800 hover:bg-gray-700'
            : 'border border-transparent text-white bg-blue-600 hover:bg-blue-700'"
        >
          <span v-if="submitting">Signing in...</span>
          <span v-else>Sign in</span>
        </button>
      </form>
    </div>
  </div>
</template>
