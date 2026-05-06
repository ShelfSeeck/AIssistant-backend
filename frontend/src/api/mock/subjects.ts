import type { Subject, Chat } from '@/types'
import type { SubjectApi } from '../types'

// Demo 数据 - 复刻原型
const demoSubjects: Subject[] = [
  {
    id: '1',
    name: '高等数学',
    desc: '微积分、线性代数、概率论综合学习记录。',
    chats: [
      {
        id: '101',
        subjectId: '1',
        title: '泰勒公式的理解与推导',
        messages: [
          {
            id: 'm1',
            role: 'user',
            content: '你能帮我通俗地讲解一下泰勒公式吗？我总是记不住。',
            timestamp: Date.now() - 86400000
          },
          {
            id: 'm2',
            role: 'ai',
            content: '当然可以。你可以把泰勒公式想象成一个"用简单的多项式去模仿复杂函数"的工具。\n\n打个比方，你要画一个人脸（复杂函数），第一笔画个圆（常数项），第二笔加上眼睛鼻子（一次项），第三笔加上表情（二次项）……画得笔画越多（阶数越高），就越像原图。\n\n核心思想是：在某一点上，让多项式的值、导数、二阶导数...都和原函数相等。',
            timestamp: Date.now() - 86300000
          }
        ],
        createdAt: Date.now() - 86400000,
        updatedAt: Date.now() - 86300000
      }
    ],
    createdAt: Date.now() - 86400000,
    updatedAt: Date.now()
  },
  {
    id: '2',
    name: '大学物理',
    desc: '力学与电磁学基础。',
    chats: [],
    createdAt: Date.now() - 172800000,
    updatedAt: Date.now() - 172800000
  },
  {
    id: '3',
    name: 'Vue 前端开发',
    desc: '组合式 API 与工程化实践。',
    chats: [],
    createdAt: Date.now() - 259200000,
    updatedAt: Date.now() - 259200000
  },
  {
    id: '4',
    name: '英语口语练习',
    desc: '日常对话与雅思备考。',
    chats: [],
    createdAt: Date.now() - 345600000,
    updatedAt: Date.now() - 345600000
  }
]

let subjects = [...demoSubjects]

export const subjectApi: SubjectApi = {
  async getAll(): Promise<Subject[]> {
    return [...subjects]
  },

  async getById(id: string): Promise<Subject | null> {
    return subjects.find(s => s.id === id) || null
  },

  async create(name: string, desc?: string): Promise<Subject> {
    const newSubject: Subject = {
      id: Date.now().toString(),
      name,
      desc: desc || '新建立的科目...',
      chats: [],
      createdAt: Date.now(),
      updatedAt: Date.now()
    }
    subjects.unshift(newSubject)
    return newSubject
  }
}
