<template>
  <header class="h-14 flex items-center justify-between px-4 flex-shrink-0">
    <div class="flex items-center gap-3 overflow-hidden">
      <!-- Hamburger 按钮 -->
      <button
        @click="toggleSidebar"
        class="p-2 rounded-xl hover:bg-highlight transition-colors flex-shrink-0 text-gray-600"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path>
        </svg>
      </button>

      <!-- 动态内容 -->
      <div class="text-sm text-gray-600 truncate font-medium flex items-center gap-2">
        <!-- Overview 视图：显示随机语录 -->
        <template v-if="routeName === 'overview'">
          {{ randomQuote }}
        </template>

        <!-- Subject 视图：显示科目名 -->
        <template v-else-if="routeName === 'subject'">
          {{ subjectStore.currentSubject?.name }}
        </template>

        <!-- Chat 视图：显示面包屑 -->
        <template v-else-if="routeName === 'chat'">
          <span
            class="text-gray-400 cursor-pointer hover:text-gray-800"
            @click="goSubjectDetail"
          >
            {{ truncate(subjectStore.currentSubject?.name || '', 8) }}
          </span>
          <span class="text-gray-400">/</span>
          <span class="text-gray-800">{{ truncate(chatStore.currentChat?.title || '', 15) }}</span>
        </template>
      </div>
    </div>

    <div class="flex items-center gap-2">
      <!-- Chat 视图：新建对话按钮 -->
      <button
        v-if="routeName === 'chat'"
        @click="goSubjectDetail"
        class="p-2 rounded-xl hover:bg-highlight transition-colors text-gray-600 flex items-center gap-1 text-sm border border-transparent hover:border-borderLight"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
        </svg>
        <span class="hidden sm:inline">新建对话</span>
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSubjectStore, useChatStore } from '@/stores'

const route = useRoute()
const router = useRouter()
const subjectStore = useSubjectStore()
const chatStore = useChatStore()

const emit = defineEmits<{
  toggleSidebar: []
}>()

const routeName = computed(() => route.name as string)

const randomQuotes = [
  "今天你学了吗？",
  "知识就是力量，少摸鱼多思考。",
  "准备好迎接新的知识挑战了吗？",
  "日拱一卒，功不唐捐。"
]

const randomQuote = ref(randomQuotes[Math.floor(Math.random() * randomQuotes.length)])

function toggleSidebar() {
  emit('toggleSidebar')
}

function goSubjectDetail() {
  const subjectId = route.params.subjectId as string
  router.push(`/subject/${subjectId}`)
}

function truncate(str: string, len: number): string {
  if (!str) return ''
  return str.length > len ? str.substring(0, len) + '...' : str
}
</script>