<script setup>
import { project } from '../lib/brand'
</script>

<template>
  <footer class="border-t border-gray-800 text-gray-500 text-xs">
    <div class="w-full px-2 py-3 sm:px-4 flex items-center justify-center">
      <a
        :href="project.github"
        target="_blank"
        rel="noopener noreferrer"
        class="inline-flex items-center gap-1.5 hover:text-white"
      >
        <span>Powered by</span>
        <img src="/logo.png" alt="" class="h-4" />
        <span>{{ project.name }}</span>
      </a>
    </div>
  </footer>
</template>
