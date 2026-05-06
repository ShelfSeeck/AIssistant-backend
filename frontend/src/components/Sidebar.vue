<template>
  <aside
    :class="[
      'bg-bgSidebar border-r border-borderLight flex flex-col transition-all duration-300 z-50 fixed md:relative h-full',
      open ? 'w-64 translate-x-0' : '-translate-x-full md:translate-x-0 md:w-0 overflow-hidden border-none'
    ]"
  >
    <div class="p-4 w-64 flex-shrink-0 flex flex-col h-full">
      <!-- Logo -->
      <div
        class="flex items-center gap-2 px-2 mb-6 mt-2 cursor-pointer"
        @click="goHome"
      >
        <span class="font-bold text-xl tracking-tight">Teachi</span>
      </div>

      <!-- 科目列表 -->
      <div class="flex-1 overflow-y-auto no-scrollbar">
        <div class="text-xs text-gray-500 font-medium px-2 mb-2">我的科目</div>
        <div class="flex flex-col gap-1">
          <button
            v-for="subject in subjectStore.previewSubjects"
            :key="subject.id"
            @click="goToSubject(subject)"
            :class="[
              'wire-btn',
              currentSubjectId === subject.id ? 'wire-btn-active' : ''
            ]"
          >
            <svg class="w-4 h-4 text-gray-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path>
            </svg>
            <span class="truncate text-sm">{{ subject.name }}</span>
          </button>

          <button
            @click="goHome"
            class="wire-btn text-sm text-gray-500 border-dashed border-borderLight hover:border-solid"
          >
            查看全部科目
          </button>
        </div>
      </div>

      <!-- 底部菜单 -->
      <div class="mt-4 pt-4 border-t border-borderLight space-y-1 flex-shrink-0">
        <button class="wire-btn text-sm">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
          </svg>
          文档
        </button>
        <button class="wire-btn text-sm">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
          </svg>
          仪表盘
        </button>
        <button class="wire-btn text-sm">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
          </svg>
          设置
        </button>

        <!-- 用户信息 -->
        <div class="mt-2 pt-2 border-t border-borderLight flex items-center gap-3 px-3 py-2 cursor-pointer hover:bg-highlight rounded-xl transition-colors">
          <div class="w-8 h-8 rounded-full bg-borderLight flex items-center justify-center text-sm">U</div>
          <div class="flex-1 min-w-0">
            <div class="text-sm font-medium truncate">User</div>
            <div class="text-xs text-gray-500 truncate">user@example.com</div>
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useSubjectStore } from '@/stores'
import type { Subject } from '@/types'

const props = defineProps<{
  open: boolean
  isMobile: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const router = useRouter()
const route = useRoute()
const subjectStore = useSubjectStore()

const currentSubjectId = computed(() => {
  if (route.name === 'subject') return route.params.id as string
  if (route.name === 'chat') return route.params.subjectId as string
  return null
})

onMounted(() => {
  subjectStore.fetchSubjects()
})

function goHome() {
  router.push('/')
  if (props.isMobile) emit('update:open', false)
}

function goToSubject(subject: Subject) {
  router.push(`/subject/${subject.id}`)
  if (props.isMobile) emit('update:open', false)
}
</script>
