<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import type { KnowledgeItem } from '../types'

defineProps<{ items: KnowledgeItem[] }>()
const emit = defineEmits<{ add: [f: { title: string; content: string; category: string }]; del: [item: KnowledgeItem] }>()

const form = ref({ title: '', content: '', category: 'business_rule' })
</script>

<template>
  <section class="page">
    <div class="page-intro"><div><span class="eyebrow"><AppIcon name="book" :size="16" /> BUSINESS KNOWLEDGE</span><h2>指标口径与业务知识</h2><p>用于 RAG 检索，让智能体理解企业专有字段、指标和规则。支持上传 Word/PDF/Markdown 文档自动解析。</p></div></div>
    <div class="knowledge-layout">
      <article class="panel knowledge-form"><h3>新增知识片段</h3>
        <input v-model="form.title" placeholder="标题，如：销售额口径"/>
        <select v-model="form.category"><option value="metric">指标口径</option><option value="business_rule">业务规则</option><option value="data_dictionary">数据字典</option><option value="example">历史问答</option></select>
        <textarea v-model="form.content" rows="7" placeholder="输入详细定义、适用范围和计算规则"/>
        <button class="primary-btn" @click="emit('add', { ...form }); form = { title: '', content: '', category: 'business_rule' }">保存并加入索引</button>
      </article>
      <div class="knowledge-list">
        <article v-for="item in items" :key="item.id" class="knowledge-card"><span><AppIcon name="book" /></span><div>
          <div class="knowledge-card-head"><strong>{{ item.title }}</strong><div><em>{{ item.category }}</em><button type="button" @click="emit('del', item)">删除</button></div></div>
          <p>{{ item.content }}</p>
        </div></article>
      </div>
    </div>
  </section>
</template>
