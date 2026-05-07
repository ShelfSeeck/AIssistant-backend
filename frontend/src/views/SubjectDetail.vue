<template>
  <div class="absolute inset-0 flex flex-col overflow-hidden">
    <!-- 内容区域 -->
    <div class="flex-1 overflow-y-auto p-4 md:p-8">
      <div class="max-w-4xl mx-auto w-full">
        <!-- 科目信息 -->
        <div class="mb-8">
          <h2 class="text-3xl font-bold mb-2">{{ subjectStore.currentSubject?.name }}</h2>
          <p class="text-gray-500 text-sm">{{ subjectStore.currentSubject?.desc }}</p>
        </div>

        <!-- 历史会话标题 -->
        <div class="text-sm text-gray-500 font-medium mb-4 border-b border-borderLight pb-2">
          历史会话
        </div>

        <!-- 会话列表 -->
        <div class="space-y-3 no-scrollbar">
          <button
            v-for="chat in chatStore.chats"
            :key="chat.id"
            @click="goToChat(chat)"
            class="w-full text-left bg-white border border-borderLight rounded-2xl p-4 hover:border-borderDark transition-colors flex justify-between items-center group"
          >
            <div class="truncate pr-4 flex-1">
              <div class="font-medium text-gray-800">{{ chat.title }}</div>
              <div class="text-xs text-gray-400 mt-1 truncate">
                {{ lastMessageContent(chat) }}
              </div>
            </div>
            <div class="text-gray-300 group-hover:text-gray-800 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
              </svg>
            </div>
          </button>

          <!-- 空状态 -->
          <div
            v-if="chatStore.chats.length === 0"
            class="text-center text-gray-400 py-10 border border-dashed border-borderLight rounded-2xl"
          >
            暂无会话，在下方输入以开始。
          </div>
        </div>
      </div>
    </div>

    <!-- 新建会话输入框 -->
    <div class="w-full bg-bgMain pt-2 pb-2 px-4">
      <div class="max-w-3xl mx-auto">
        <ChatInput
          ref="chatInputRef"
          v-model="newChatMsg"
          placeholder="新建会话..."
          :disabled="false"
          @send="startNewChat"
        />
        <div class="text-center text-[10px] text-gray-400 mt-2">
          Ctrl+Enter 发送，Enter 换行
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSubjectStore, useChatStore } from '@/stores'
import ChatInput from '@/components/ChatInput.vue'
import type { Chat } from '@/types'

const route = useRoute()
const router = useRouter()
const subjectStore = useSubjectStore()
const chatStore = useChatStore()

const chatInputRef = ref<{ resetHeight: () => void }>()
const newChatMsg = ref('')
const subjectId = ref(route.params.id as string)

onMounted(async () => {
  const id = route.params.id as string
  subjectId.value = id

  // 加载科目
  const subject = await subjectStore.loadSubject(id)
  if (subject) {
    // 加载该科目的会话
    await chatStore.fetchChats(id)
  }
})

watch(() => route.params.id, async (newId) => {
  if (newId && newId !== subjectId.value) {
    subjectId.value = newId as string
    const subject = await subjectStore.loadSubject(newId as string)
    if (subject) {
      await chatStore.fetchChats(newId as string)
    }
  }
})

function lastMessageContent(chat: Chat): string {
  const lastMsg = chat.messages[chat.messages.length - 1]
  return lastMsg?.content || '空会话'
}

function goToChat(chat: Chat) {
  router.push(`/chat/${subjectId.value}/${chat.id}`)
}

async function startNewChat(content: string) {
  if (!content.trim()) return

  const newChat = await chatStore.createChat(subjectId.value, content)
  newChatMsg.value = ''

  // 重置输入框高度
  chatInputRef.value?.resetHeight()

  router.push(`/chat/${subjectId.value}/${newChat.id}`)
}
</script>
