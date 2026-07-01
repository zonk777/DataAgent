import { ref, onUnmounted } from 'vue'

export interface UseTypewriterOptions {
  speed?: number
}

export function useTypewriter(options: UseTypewriterOptions = {}) {
  const { speed = 30 } = options
  const displayText = ref('')
  const isTyping = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null
  let fullText = ''
  let cursor = 0

  function startTyping(text: string) {
    stopTyping()
    fullText = text
    cursor = 0
    displayText.value = ''
    isTyping.value = true
    tick()
    timer = setInterval(tick, 1000 / speed)
  }

  function tick() {
    if (cursor >= fullText.length) {
      complete()
      return
    }
    // Advance by 1-3 chars per tick for natural feel
    const chunk = fullText.length - cursor > 30 ? 2 : 1
    cursor = Math.min(cursor + chunk, fullText.length)
    displayText.value = fullText.slice(0, cursor)
  }

  function complete() {
    if (timer) { clearInterval(timer); timer = null }
    displayText.value = fullText
    isTyping.value = false
  }

  function stopTyping() {
    if (timer) { clearInterval(timer); timer = null }
    isTyping.value = false
  }

  function reset() {
    stopTyping()
    fullText = ''
    cursor = 0
    displayText.value = ''
  }

  onUnmounted(() => stopTyping())

  return { displayText, startTyping, complete, isTyping, reset }
}
