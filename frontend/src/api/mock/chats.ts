import type { Chat, Message } from '@/types'
import type { ChatApi } from '../types'
import { subjectApi } from './subjects'

export const chatApi: ChatApi = {
  async getBySubjectId(subjectId: string): Promise<Chat[]> {
    const subject = await subjectApi.getById(subjectId)
    return subject?.chats || []
  },

  async getById(chatId: string): Promise<Chat | null> {
    const subjects = await subjectApi.getAll()
    for (const subject of subjects) {
      const chat = subject.chats.find(c => c.id === chatId)
      if (chat) return chat
    }
    return null
  },

  async create(subjectId: string, firstMessage: string): Promise<Chat> {
    const subject = await subjectApi.getById(subjectId)
    if (!subject) throw new Error('Subject not found')

    const newChat: Chat = {
      id: Date.now().toString(),
      subjectId,
      title: firstMessage.substring(0, 15) + (firstMessage.length > 15 ? '...' : ''),
      messages: [
        {
          id: Date.now().toString(),
          role: 'user',
          content: firstMessage,
          timestamp: Date.now()
        }
      ],
      createdAt: Date.now(),
      updatedAt: Date.now()
    }

    subject.chats.unshift(newChat)
    return newChat
  },

  async sendMessage(chatId: string, content: string): Promise<Message> {
    const subjects = await subjectApi.getAll()
    for (const subject of subjects) {
      const chat = subject.chats.find(c => c.id === chatId)
      if (chat) {
        const userMsg: Message = {
          id: Date.now().toString(),
          role: 'user',
          content,
          timestamp: Date.now()
        }
        chat.messages.push(userMsg)

        // 模拟 AI 响应
        await new Promise(resolve => setTimeout(resolve, 1500))

        const aiMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: 'ai',
          content: '收到，这是一个演示响应。我是您的 AI 助教 Teachi。',
          timestamp: Date.now()
        }
        chat.messages.push(aiMsg)
        chat.updatedAt = Date.now()

        return aiMsg
      }
    }
    throw new Error('Chat not found')
  },

  async retryMessage(chatId: string, messageId: string): Promise<Message> {
    const subjects = await subjectApi.getAll()
    for (const subject of subjects) {
      const chat = subject.chats.find(c => c.id === chatId)
      if (chat) {
        const msgIndex = chat.messages.findIndex(m => m.id === messageId)
        if (msgIndex > 0 && chat.messages[msgIndex].role === 'ai') {
          // 删除该 AI 消息及之后的所有消息
          chat.messages.splice(msgIndex)

          await new Promise(resolve => setTimeout(resolve, 1500))

          const aiMsg: Message = {
            id: Date.now().toString(),
            role: 'ai',
            content: '这是重试后生成的内容。请问还有什么疑问？',
            timestamp: Date.now()
          }
          chat.messages.push(aiMsg)
          chat.updatedAt = Date.now()
          return aiMsg
        }
      }
    }
    throw new Error('Message not found')
  }
}
