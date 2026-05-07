<template>
  <div class="absolute inset-0 flex flex-col">

    <!-- 消息列表 -->
    <div class="flex-1 overflow-y-auto p-4 md:p-6 scroll-smooth" ref="chatContainer">
      <div class="max-w-3xl mx-auto space-y-3 pb-4">
        <div
          v-for="(msg, index) in chatStore.messages"
          :key="msg.id"
          class="flex flex-col"
        >
          <!-- 用户消息 - 右边 -->
          <div v-if="msg.role === 'user'" class="flex justify-end w-full">
            <div class="max-w-[85%] bg-highlightUser border border-borderLight text-gray-800 px-5 py-3 rounded-2xl rounded-tr-sm text-[15px] leading-relaxed">
              {{ msg.content }}
            </div>
          </div>

          <!-- AI 消息 - 左边 -->
          <div v-else class="flex justify-start w-full">
            <div class="max-w-[85%] bg-white border border-borderDark text-gray-800 px-5 py-4 rounded-2xl rounded-tl-sm text-[15px] leading-relaxed relative group">
              <p class="whitespace-pre-wrap">{{ msg.content }}</p>
              <div class="absolute -bottom-8 right-0 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  @click="retryMessage(msg.id)"
                  class="p-1.5 text-gray-400 hover:text-gray-800 bg-bgMain rounded-lg border border-transparent hover:border-borderLight"
                  title="重试"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
                  </svg>
                </button>
                <button
                  class="p-1.5 text-gray-400 hover:text-gray-800 bg-bgMain rounded-lg border border-transparent hover:border-borderLight"
                  title="复制"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入中指示器 - 左边 -->
        <div v-if="chatStore.isTyping" class="flex justify-start w-full">
          <div class="bg-white border border-borderLight px-5 py-3 rounded-2xl rounded-tl-sm flex gap-1 items-center">
            <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
            <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0.2s"></div>
            <div class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0.4s"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="w-full bg-bgMain pt-2 pb-2 px-4">
      <div class="max-w-3xl mx-auto">
        <ChatInput
          ref="chatInputRef"
          v-model="chatInput"
          placeholder="给 Teachi 发送消息..."
          :disabled="chatStore.isTyping"
          @send="sendMessage"
        />
        <div class="text-center text-[10px] text-gray-400 mt-2">
          Teachi 可能会犯错。请核查重要信息。
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, nextTick, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useSubjectStore, useChatStore } from '@/stores'
import ChatInput from '@/components/ChatInput.vue'

const route = useRoute()
const subjectStore = useSubjectStore()
const chatStore = useChatStore()

const chatInputRef = ref<{ resetHeight: () => void }>()
const chatInput = ref('')
const chatContainer = ref<HTMLElement>()

const subjectId = computed(() => route.params.subjectId as string)
const chatId = computed(() => route.params.chatId as string)

onMounted(async () => {
  await loadData()
})

watch(() => [route.params.subjectId, route.params.chatId], async () => {
  await loadData()
})

async function loadData() {
  // 加载科目
  await subjectStore.loadSubject(subjectId.value)
  // 加载对话
  await chatStore.loadChat(chatId.value)
  scrollToBottom()
}

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

async function sendMessage(content: string) {
  if (!content.trim() || chatStore.isTyping) return

  chatInput.value = ''
  // 重置输入框高度
  chatInputRef.value?.resetHeight()

  await chatStore.sendMessage(content)
  scrollToBottom()
}

async function retryMessage(messageId: string) {
  if (chatStore.isTyping) return

  await chatStore.retryMessage(messageId)
  scrollToBottom()
}
</script>
