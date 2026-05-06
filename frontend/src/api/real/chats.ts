import type { Chat, Message } from '@/types'
import type { ChatApi } from '../types'

export const chatApi: ChatApi = {
  async getBySubjectId(subjectId: string): Promise<Chat[]> {
    throw new Error('Real API not implemented yet')
  },

  async getById(chatId: string): Promise<Chat | null> {
    throw new Error('Real API not implemented yet')
  },

  async create(subjectId: string, firstMessage: string): Promise<Chat> {
    throw new Error('Real API not implemented yet')
  },

  async sendMessage(chatId: string, content: string): Promise<Message> {
    throw new Error('Real API not implemented yet')
  },

  async retryMessage(chatId: string, messageId: string): Promise<Message> {
    throw new Error('Real API not implemented yet')
  }
}
