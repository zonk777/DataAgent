<script setup lang="ts">
import { watch, onMounted } from 'vue'
import { useTypewriter } from '../composables/useTypewriter'

const props = withDefaults(defineProps<{
  text: string
  speed?: number
  enabled?: boolean
}>(), {
  speed: 30,
  enabled: true,
})

const { displayText, startTyping, complete, isTyping } = useTypewriter({ speed: props.speed })

onMounted(() => {
  if (props.enabled && props.text) startTyping(props.text)
  else if (props.text) complete()
})

watch(() => props.text, (newText) => {
  if (props.enabled) startTyping(newText)
  else displayText.value = newText
})
</script>

<template>
  <span class="typewriter-text">
    {{ displayText }}<span v-if="isTyping && enabled" class="typewriter-cursor">|</span>
  </span>
</template>
