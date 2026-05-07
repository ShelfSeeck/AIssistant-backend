<template>
  <div class="relative bg-white rounded-2xl border border-borderDark p-3 shadow-sm flex flex-col gap-2 transition-shadow focus-within:ring-2 focus-within:ring-highlight">
    <textarea
      ref="textareaRef"
      v-model="inputValue"
      @keydown.enter="handleKeydown"
      :placeholder="placeholder"
      :disabled="disabled"
      class="w-full bg-transparent border-none outline-none text-gray-800 resize-none overflow-y-auto leading-normal placeholder-gray-400 transition-all duration-200"
      :style="{ minHeight: '24px', maxHeight: maxHeight }"
    ></textarea>
    <div class="flex justify-between items-center">
      <div class="flex items-center gap-1">
        <button
          v-if="showAttachment"
          class="p-1.5 text-gray-400 hover:text-gray-800 rounded-lg hover:bg-highlight transition-colors"
          title="上传文件"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path>
          </svg>
        </button>
        <slot name="extra-tools"></slot>
      </div>
      <button
        @click="handleSend"
        :class="[
          'p-2 rounded-lg transition-colors flex items-center justify-center -mr-1',
          canSend && !disabled
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
import { computed, ref, watch, nextTick, onMounted } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: string
  placeholder?: string
  maxHeight?: string
  disabled?: boolean
  sendOnEnter?: boolean
  showAttachment?: boolean
}>(), {
  placeholder: '发送消息...',
  maxHeight: '128px',
  disabled: false,
  sendOnEnter: false,
  showAttachment: true
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: [value: string]
}>()

const textareaRef = ref<HTMLTextAreaElement>()

const inputValue = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const canSend = computed(() => {
  return inputValue.value.trim().length > 0
})

// 初始化最小高度
onMounted(() => {
  if (textareaRef.value) {
    textareaRef.value.style.height = '24px'
    textareaRef.value.style.overflowY = 'hidden'
  }
})

// 自动调整高度
function adjustHeight() {
  nextTick(() => {
    if (!textareaRef.value) return
    const textarea = textareaRef.value

    // 内容为空时强制最小高度
    if (!inputValue.value.trim()) {
      textarea.style.height = '24px'
      textarea.style.overflowY = 'hidden'
      return
    }

    // 重置高度以获取正确的 scrollHeight
    textarea.style.height = '24px'

    // 设置新高度（向上平滑增大）
    const newHeight = Math.min(textarea.scrollHeight, parseInt(props.maxHeight))
    textarea.style.height = `${newHeight}px`

    // 如果超过 maxHeight，显示滚动条
    if (textarea.scrollHeight > parseInt(props.maxHeight)) {
      textarea.style.overflowY = 'auto'
    } else {
      textarea.style.overflowY = 'hidden'
    }
  })
}

// 监听内容变化
watch(inputValue, () => {
  adjustHeight()
})

function handleKeydown(e: KeyboardEvent) {
  if (props.sendOnEnter) {
    // Enter 发送模式（用于新建科目/会话）
    if (!e.ctrlKey && !e.metaKey) {
      e.preventDefault()
      handleSend()
    }
  } else {
    // Ctrl+Enter 发送模式（用于聊天）
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault()
      handleSend()
    }
    // 单独 Enter 允许换行
  }
}

function handleSend() {
  if (!canSend.value || props.disabled) return
  emit('send', inputValue.value.trim())
}

// 清空内容后重置高度
function resetHeight() {
  if (textareaRef.value) {
    textareaRef.value.style.height = '24px'
    textareaRef.value.style.overflowY = 'hidden'
  }
}

// 暴露 resetHeight 方法供外部调用
defineExpose({ resetHeight })
</script>