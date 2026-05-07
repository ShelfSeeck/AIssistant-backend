<template>
  <div class="absolute inset-0 flex flex-col overflow-hidden">
    <!-- 内容区域 -->
    <div class="flex-1 overflow-y-auto p-4 md:p-8 lg:px-24">
      <div class="flex flex-col justify-center max-w-5xl mx-auto w-full min-h-full">
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
    </div>

    <!-- 新建科目输入框 -->
    <div class="w-full bg-bgMain pt-2 pb-2 px-4">
      <div class="max-w-3xl mx-auto">
        <ChatInput
          ref="chatInputRef"
          v-model="newSubjectName"
          placeholder="新建科目..."
          :disabled="false"
          @send="createSubject"
        />
        <div class="text-center text-[10px] text-gray-400 mt-2">
          Ctrl+Enter 发送，Enter 换行
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSubjectStore } from '@/stores'
import ChatInput from '@/components/ChatInput.vue'
import type { Subject } from '@/types'

const router = useRouter()
const subjectStore = useSubjectStore()
const chatInputRef = ref<{ resetHeight: () => void }>()

const newSubjectName = ref('')

onMounted(() => {
  subjectStore.fetchSubjects()
})

function goToSubject(subject: Subject) {
  router.push(`/subject/${subject.id}`)
}

async function createSubject(content: string) {
  if (!content) return

  const newSubject = await subjectStore.createSubject(content)
  newSubjectName.value = ''

  // 重置输入框高度
  chatInputRef.value?.resetHeight()

  router.push(`/subject/${newSubject.id}`)
}
</script>
