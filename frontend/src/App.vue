<template>
  <div class="bg-bgMain h-screen flex">
    <!-- 移动端遮罩 -->
    <div
      v-if="sidebarOpen && isMobile"
      @click="sidebarOpen = false"
      class="fixed inset-0 bg-black/20 z-40"
    ></div>

    <!-- 侧边栏 -->
    <Sidebar
      v-model:open="sidebarOpen"
      :is-mobile="isMobile"
    />

    <!-- 主内容区 -->
    <main class="flex-1 flex flex-col min-w-0 bg-bgMain relative transition-all duration-300">
      <!-- 统一 Header -->
      <Header @toggle-sidebar="sidebarOpen = !sidebarOpen" />

      <!-- 路由视图 -->
      <div class="flex-1 overflow-hidden relative">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Sidebar from './components/Sidebar.vue'
import Header from './components/Header.vue'

const sidebarOpen = ref(true)
const windowWidth = ref(window.innerWidth)

const isMobile = computed(() => windowWidth.value < 768)

const handleResize = () => {
  windowWidth.value = window.innerWidth
  sidebarOpen.value = windowWidth.value >= 768
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  handleResize()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>
