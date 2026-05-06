import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'overview',
    component: () => import('@/views/Overview.vue')
  },
  {
    path: '/subject/:id',
    name: 'subject',
    component: () => import('@/views/SubjectDetail.vue')
  },
  {
    path: '/chat/:subjectId/:chatId',
    name: 'chat',
    component: () => import('@/views/Chat.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
