import type { Subject, Chat, Message } from '@/types'

export interface SubjectApi {
  getAll(): Promise<Subject[]>
  getById(id: string): Promise<Subject | null>
  create(name: string, desc?: string): Promise<Subject>
}

export interface ChatApi {
  getBySubjectId(subjectId: string): Promise<Chat[]>
  getById(chatId: string): Promise<Chat | null>
  create(subjectId: string, firstMessage: string): Promise<Chat>
  sendMessage(chatId: string, content: string): Promise<Message>
  retryMessage(chatId: string, messageId: string): Promise<Message>
}
