import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Chat, Message } from '@/types'
import { chatApi } from '@/api'

export const useChatStore = defineStore('chat', () => {
  // State
  const chats = ref<Chat[]>([])
  const currentChat = ref<Chat | null>(null)
  const isTyping = ref(false)
  const loading = ref(false)

  // Getters
  const messages = computed(() => currentChat.value?.messages || [])

  // Actions
  async function fetchChats(subjectId: string) {
    loading.value = true
    try {
      chats.value = await chatApi.getBySubjectId(subjectId)
    } finally {
      loading.value = false
    }
  }

  async function loadChat(chatId: string) {
    const chat = await chatApi.getById(chatId)
    if (chat) {
      currentChat.value = chat
    }
    return chat
  }

  async function createChat(subjectId: string, firstMessage: string) {
    const newChat = await chatApi.create(subjectId, firstMessage)
    chats.value.unshift(newChat)
    currentChat.value = newChat
    return newChat
  }

  async function sendMessage(content: string) {
    if (!currentChat.value || isTyping.value) return

    const chatId = currentChat.value.id
    isTyping.value = true

    try {
      await chatApi.sendMessage(chatId, content)
    } finally {
      isTyping.value = false
    }
  }

  async function retryMessage(messageId: string) {
    if (!currentChat.value || isTyping.value) return

    const chatId = currentChat.value.id
    isTyping.value = true

    try {
      await chatApi.retryMessage(chatId, messageId)
    } finally {
      isTyping.value = false
    }
  }

  function setCurrentChat(chat: Chat | null) {
    currentChat.value = chat
  }

  function clearChats() {
    chats.value = []
    currentChat.value = null
  }

  return {
    chats,
    currentChat,
    isTyping,
    loading,
    messages,
    fetchChats,
    loadChat,
    createChat,
    sendMessage,
    retryMessage,
    setCurrentChat,
    clearChats
  }
})
