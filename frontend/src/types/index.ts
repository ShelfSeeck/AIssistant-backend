export interface Subject {
  id: string
  name: string
  desc: string
  chats: Chat[]
  createdAt: number
  updatedAt: number
}

export interface Chat {
  id: string
  subjectId: string
  title: string
  messages: Message[]
  createdAt: number
  updatedAt: number
}

export interface Message {
  id: string
  role: 'user' | 'ai'
  content: string
  timestamp: number
}

export type ViewState = 'overview' | 'subject' | 'chat'

export interface CreateSubjectRequest {
  name: string
  desc?: string
}

export interface CreateChatRequest {
  subjectId: string
  firstMessage: string
}

export interface SendMessageRequest {
  chatId: string
  content: string
}
