import type { Subject } from '@/types'
import type { SubjectApi } from '../types'

export const subjectApi: SubjectApi = {
  async getAll(): Promise<Subject[]> {
    throw new Error('Real API not implemented yet')
  },

  async getById(id: string): Promise<Subject | null> {
    throw new Error('Real API not implemented yet')
  },

  async create(name: string, desc?: string): Promise<Subject> {
    throw new Error('Real API not implemented yet')
  }
}
