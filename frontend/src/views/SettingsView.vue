<script setup lang="ts">
import AppIcon from '../components/AppIcon.vue'
import type { ConfigStatus } from '../types'

defineProps<{ config: ConfigStatus | null }>()
</script>

<template>
  <section class="page">
    <div class="page-intro"><div><span class="eyebrow"><AppIcon name="settings" :size="16" /> SYSTEM SETTINGS</span><h2>模型与基础设施</h2><p>密钥仅从后端环境变量读取，不会返回给浏览器。</p></div></div>
    <div class="settings-grid">
      <article class="panel setting-card"><div class="setting-head"><span class="metric-icon blue"><AppIcon name="spark" /></span><div><h3>大语言模型</h3><p>OpenAI 兼容接口</p></div><em :class="{ ready: config?.llm_configured }">{{ config?.llm_configured ? '已配置' : '待配置' }}</em></div><dl><div><dt>模型</dt><dd>{{ config?.llm_model || '未设置' }}</dd></div><div><dt>API Key</dt><dd>仅后端可见</dd></div></dl></article>
      <article class="panel setting-card"><div class="setting-head"><span class="metric-icon cyan"><AppIcon name="book" /></span><div><h3>Embedding / RAG</h3><p>语义向量检索</p></div><em :class="{ ready: config?.embedding_configured }">{{ config?.embedding_configured ? '已启用' : '关键词降级' }}</em></div><dl><div><dt>Embedding 模型</dt><dd>{{ config?.embedding_model || '未配置' }}</dd></div><div><dt>向量存储</dt><dd>{{ config?.vector_store }}</dd></div><div><dt>已索引知识</dt><dd>{{ config?.vector_indexed_count ?? 0 }} 条</dd></div></dl></article>
      <article class="panel setup-card"><h3>API Key 配置位置</h3><p>复制 <code>backend/.env.example</code> 为 <code>backend/.env</code>，然后填写：</p><pre>LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=你要使用的模型</pre><p class="security-note">不要把 <code>.env</code> 提交到 Git；项目已在 <code>.gitignore</code> 中排除该文件。</p></article>
    </div>
  </section>
</template>
