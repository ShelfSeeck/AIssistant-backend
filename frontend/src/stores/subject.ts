import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Subject } from '@/types'
import { subjectApi } from '@/api'

export const useSubjectStore = defineStore('subject', () => {
  // State
  const subjects = ref<Subject[]>([])
  const currentSubject = ref<Subject | null>(null)
  const loading = ref(false)

  // Getters
  const previewSubjects = computed(() => subjects.value.slice(0, 10))

  // Actions
  async function fetchSubjects() {
    loading.value = true
    try {
      subjects.value = await subjectApi.getAll()
    } finally {
      loading.value = false
    }
  }

  function setCurrentSubject(subject: Subject | null) {
    currentSubject.value = subject
  }

  async function loadSubject(id: string) {
    const subject = await subjectApi.getById(id)
    if (subject) {
      setCurrentSubject(subject)
    }
    return subject
  }

  async function createSubject(name: string, desc?: string) {
    const newSubject = await subjectApi.create(name, desc)
    subjects.value.unshift(newSubject)
    return newSubject
  }

  return {
    subjects,
    currentSubject,
    loading,
    previewSubjects,
    fetchSubjects,
    setCurrentSubject,
    loadSubject,
    createSubject
  }
})
