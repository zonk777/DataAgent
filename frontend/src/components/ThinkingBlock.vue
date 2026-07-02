<script setup lang="ts">
import { watch, computed } from 'vue'
import type { ThinkingStep } from '../types'
import { useTypewriter } from '../composables/useTypewriter'
import AppIcon from './AppIcon.vue'

const props = defineProps<{
  steps: ThinkingStep[]
  thinkingText: string
  isStreaming: boolean
  collapsed: boolean
}>()

const emit = defineEmits<{
  toggle: []
}>()

const { displayText, startTyping, complete, reset } = useTypewriter({ speed: 40 })

let lastText = ''
watch(() => props.thinkingText, (text) => {
  if (!text) { reset(); lastText = ''; return }
  if (text === lastText) return
  // Append small deltas instantly, retype for larger changes
  if (text.startsWith(lastText)) {
    const delta = text.slice(lastText.length)
    if (delta.length <= 60) {
      displayText.value = text
    } else {
      startTyping(text)
    }
  } else {
    startTyping(text)
  }
  lastText = text
})

// Auto-collapse after streaming ends
let collapseTimer: ReturnType<typeof setTimeout> | null = null
watch(() => props.isStreaming, (streaming) => {
  if (!streaming && !props.collapsed) {
    collapseTimer = setTimeout(() => emit('toggle'), 2000)
  }
  if (streaming && collapseTimer) {
    clearTimeout(collapseTimer)
    collapseTimer = null
  }
})

const doneCount = computed(() => props.steps.filter(s => s.status === 'completed').length)
const totalCount = computed(() => props.steps.length)
const intentLabel = computed(() => {
  const first = props.steps[0]
  return first?.detail || ''
})

function statusIcon(status: string) {
  switch (status) {
    case 'running': return '…'
    case 'completed': return '✓'
    case 'error': return '!'
    default: return '•'
  }
}
</script>

<template>
  <div class="thinking-block" :class="{ collapsed, streaming: isStreaming }">
    <button class="thinking-block-header" @click="emit('toggle')">
      <span class="thinking-ring" :class="{ spinning: isStreaming }">
        <span>{{ doneCount }}</span>
      </span>
      <span class="summary">
        <template v-if="collapsed">
          已完成 {{ doneCount }}/{{ totalCount }} 步分析
          <em v-if="intentLabel"> · {{ intentLabel }}</em>
        </template>
        <template v-else>
          {{ isStreaming ? '智能体正在思考' : '分析进度' }} {{ doneCount }}/{{ totalCount }}
        </template>
      </span>
      <span class="arrow">{{ collapsed ? '展开' : '收起' }}</span>
    </button>
    <div v-if="!collapsed" class="thinking-block-body">
      <div class="thinking-steps">
        <div
          v-for="step in steps"
          :key="step.id"
          class="thinking-step"
          :class="step.status"
        >
          <span class="dot">{{ statusIcon(step.status) }}</span>
          <span class="title">{{ step.title }}</span>
          <span v-if="step.detail" class="detail">{{ step.detail }}</span>
        </div>
      </div>
      <div v-if="displayText" class="thinking-text">
        <AppIcon name="spark" :size="12" />
        <span>{{ displayText }}</span>
        <span v-if="isStreaming" class="typewriter-cursor">|</span>
      </div>
    </div>
  </div>
</template>
