<template>
  <div class="absolute inset-0 overflow-y-auto p-4 md:p-8 lg:px-24 flex flex-col">
    <div class="flex-1 flex flex-col justify-center max-w-5xl mx-auto w-full">
      <h1 class="text-4xl md:text-5xl font-bold mb-10 tracking-tight">科目总览</h1>

      <!-- 科目卡片横向滚动 -->
      <div class="flex overflow-x-auto pb-2 -mx-4 px-4 md:mx-0 md:px-0 gap-4 snap-x no-scrollbar">
        <div
          v-for="subject in subjectStore.subjects"
          :key="subject.id"
          @click="goToSubject(subject)"
          class="wire-card min-w-[280px] w-[280px] h-[160px] flex-shrink-0 snap-start flex flex-col justify-between"
        >
          <div>
            <h3 class="font-bold text-lg mb-2">{{ subject.name }}</h3>
            <p class="text-sm text-gray-500 line-clamp-2">{{ subject.desc }}</p>
          </div>
          <div class="text-xs text-gray-400 border-t border-borderLight pt-3 flex justify-between">
            <span>{{ subject.chats.length }} 个会话</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建科目输入框 -->
    <div class="max-w-4xl mx-auto w-full pb-2">
      <div class="relative bg-white rounded-2xl border border-borderDark p-4 shadow-sm flex flex-col gap-3 transition-shadow focus-within:ring-2 focus-within:ring-highlight">
        <textarea
          v-model="newSubjectName"
          @keydown.enter.prevent="createSubject"
          rows="1"
          placeholder="新建科目：输入科目名称与概览..."
          class="w-full bg-transparent border-none outline-none text-gray-800 resize-none overflow-y-auto leading-normal placeholder-gray-400 min-h-[24px]"
        ></textarea>
        <div class="flex justify-between items-center">
          <div class="flex items-center -ml-2 gap-1">
            <button class="p-2 text-gray-400 hover:text-gray-800 rounded-lg hover:bg-highlight transition-colors" title="上传文件">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path>
              </svg>
            </button>
            <button class="p-2 text-gray-400 hover:text-gray-800 rounded-lg hover:bg-highlight transition-colors" title="语音输入">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"></path>
              </svg>
            </button>
          </div>
          <button
            @click="createSubject"
            :class="[
              'p-2 rounded-lg transition-colors flex items-center justify-center -mr-1',
              canCreate
                ? 'bg-borderDark text-white hover:bg-gray-700'
                : 'bg-gray-100 text-gray-400 cursor-not-allowed'
            ]"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path>
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSubjectStore } from '@/stores'
import type { Subject } from '@/types'

const router = useRouter()
const subjectStore = useSubjectStore()

const newSubjectName = ref('')

const canCreate = computed(() => newSubjectName.value.trim().length > 0)

onMounted(() => {
  subjectStore.fetchSubjects()
})

function goToSubject(subject: Subject) {
  router.push(`/subject/${subject.id}`)
}

async function createSubject() {
  if (!canCreate.value) return

  const name = newSubjectName.value.trim()
  const newSubject = await subjectStore.createSubject(name)
  newSubjectName.value = ''

  router.push(`/subject/${newSubject.id}`)
}
</script>
