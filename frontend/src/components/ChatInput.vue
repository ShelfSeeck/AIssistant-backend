<template>
  <div class="relative bg-white rounded-2xl border border-borderDark p-3 shadow-sm flex flex-col gap-2 transition-shadow focus-within:ring-2 focus-within:ring-highlight">
    <textarea
      v-model="inputValue"
      @keydown.enter.prevent="handleSend"
      :rows="rows"
      :placeholder="placeholder"
      class="w-full bg-transparent border-none outline-none text-gray-800 resize-none max-h-32 overflow-y-auto leading-normal placeholder-gray-400"
    ></textarea>
    <div class="flex justify-between items-center">
      <div class="flex items-center -ml-2 gap-1">
        <button
          class="p-2 text-gray-400 hover:text-gray-800 rounded-lg hover:bg-highlight transition-colors"
          title="上传文件"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path>
          </svg>
        </button>
        <button
          class="p-2 text-gray-400 hover:text-gray-800 rounded-lg hover:bg-highlight transition-colors"
          title="语音输入"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"></path>
          </svg>
        </button>
        <slot name="extra-tools"></slot>
      </div>
      <button
        @click="handleSend"
        :class="[
          'p-2 rounded-lg transition-colors flex items-center justify-center -mr-1',
          canSend
            ? 'bg-borderDark text-white hover:bg-gray-700'
            : 'bg-gray-100 text-gray-400 cursor-not-allowed'
        ]"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path>
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: string
  placeholder?: string
  rows?: number
  disabled?: boolean
}>(), {
  placeholder: '发送消息...',
  rows: 1,
  disabled: false
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: [value: string]
}>()

const inputValue = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const canSend = computed(() => {
  return inputValue.value.trim().length > 0 && !props.disabled
})

function handleSend() {
  if (!canSend.value) return
  emit('send', inputValue.value.trim())
}
</script>
