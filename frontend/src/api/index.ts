import type { SubjectApi, ChatApi } from './types'
import { subjectApi as mockSubjectApi } from './mock/subjects'
import { chatApi as mockChatApi } from './mock/chats'
import { subjectApi as realSubjectApi } from './real/subjects'
import { chatApi as realChatApi } from './real/chats'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

export const subjectApi: SubjectApi = USE_MOCK ? mockSubjectApi : realSubjectApi
export const chatApi: ChatApi = USE_MOCK ? mockChatApi : realChatApi
