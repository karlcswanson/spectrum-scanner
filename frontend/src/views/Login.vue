<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { brand, project } from '../lib/brand'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const submitting = ref(false)

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
        <img :src="brand.logoUrl" :alt="brand.logoAlt" class="w-full mb-6" />
        <h2 class="text-3xl font-bold text-white">
          {{ brand.name }}
        </h2>
        <p class="mt-2 text-sm text-gray-400">
          Sign in to view spectrum data
        </p>
      </div>

      <form class="mt-8 space-y-6" @submit.prevent="handleSubmit">
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
          :style="brand.accent ? { backgroundColor: brand.accent } : {}"
          class="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <span v-if="submitting">Signing in...</span>
          <span v-else>Sign in</span>
        </button>
      </form>

      <a
        :href="project.github"
        target="_blank"
        rel="noopener noreferrer"
        class="flex items-center justify-center gap-1.5 text-xs text-gray-600 hover:text-gray-300"
      >
        <span>Powered by</span>
        <img src="/logo.png" alt="" class="h-4" />
        <span>{{ project.name }}</span>
      </a>
    </div>
  </div>
</template>
