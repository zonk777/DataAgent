<script setup lang="ts">
import { computed, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import type { KnowledgeItem } from '../types'

const props = defineProps<{ items: KnowledgeItem[] }>()
const emit = defineEmits<{ add: [f: { title: string; content: string; category: string }]; del: [item: KnowledgeItem] }>()

const form = ref({ title: '', content: '', category: 'business_rule' })
const selectedItem = ref<KnowledgeItem | null>(null)
const knowledgeQuery = ref('')

const filteredItems = computed(() => {
  const q = knowledgeQuery.value.trim().toLowerCase()
  if (!q) return props.items
  return props.items.filter(item => {
    const text = [item.title, item.content, item.category].filter(Boolean).join(' ').toLowerCase()
    return text.includes(q)
  })
})

function firstLine(content: string) {
  const normalized = (content || '').replace(/\s+/g, ' ').trim()
  return normalized || '暂无内容'
}

function isLongContent(content: string) {
  const raw = content || ''
  return raw.length > 80 || /\r?\n/.test(raw)
}

function addKnowledge() {
  emit('add', { ...form.value })
  form.value = { title: '', content: '', category: 'business_rule' }
}
</script>

<template>
  <section class="page">
    <div class="page-intro">
      <div>
        <span class="eyebrow"><AppIcon name="book" :size="16" /> BUSINESS KNOWLEDGE</span>
        <h2>指标口径与业务知识</h2>
        <p>用于 RAG 检索，让智能体理解企业专有字段、指标和规则。支持上传 Word/PDF/Markdown 文档自动解析。</p>
      </div>
    </div>

    <div class="knowledge-layout">
      <article class="panel knowledge-form">
        <h3>新增知识片段</h3>
        <input v-model="form.title" placeholder="标题，如：销售额口径" />
        <select v-model="form.category">
          <option value="metric">指标口径</option>
          <option value="business_rule">业务规则</option>
          <option value="data_dictionary">数据字典</option>
          <option value="example">历史问答</option>
        </select>
        <textarea v-model="form.content" rows="7" placeholder="输入详细定义、适用范围和计算规则" />
        <button class="primary-btn" @click="addKnowledge">保存并加入索引</button>
      </article>

      <div class="knowledge-list-wrap">
        <div class="knowledge-toolbar">
          <div>
            <small>KNOWLEDGE BASE</small>
            <strong>业务知识片段</strong>
          </div>
          <label class="knowledge-search">
            <AppIcon name="search" :size="15" />
            <input v-model="knowledgeQuery" placeholder="搜索标题、内容或分类" />
            <button v-if="knowledgeQuery" type="button" aria-label="清空搜索" @click="knowledgeQuery = ''">×</button>
          </label>
        </div>

        <div v-if="filteredItems.length" class="knowledge-list">
          <article v-for="item in filteredItems" :key="item.id" class="knowledge-card compact-knowledge-card">
            <span><AppIcon name="book" /></span>
            <div class="knowledge-card-main">
              <div class="knowledge-card-head">
                <strong>{{ item.title }}</strong>
                <div>
                  <em>{{ item.category }}</em>
                  <button
                    v-if="isLongContent(item.content)"
                    type="button"
                    class="icon-only-btn"
                    title="查看完整内容"
                    aria-label="查看完整内容"
                    @click="selectedItem = item"
                  >
                    <AppIcon name="eye" :size="15" />
                  </button>
                  <button type="button" @click="emit('del', item)">删除</button>
                </div>
              </div>
              <p class="knowledge-preview-line">{{ firstLine(item.content) }}</p>
            </div>
          </article>
        </div>

        <div v-else class="knowledge-empty">
          <AppIcon name="search" :size="30" />
          <strong>没有找到匹配的知识片段</strong>
          <p>换个关键词，或者清空搜索条件后再试。</p>
        </div>
      </div>
    </div>

    <div v-if="selectedItem" class="knowledge-modal-mask" @click.self="selectedItem = null">
      <article class="knowledge-modal">
        <header>
          <div>
            <small>{{ selectedItem.category }}</small>
            <h3>{{ selectedItem.title }}</h3>
          </div>
          <button type="button" aria-label="关闭" @click="selectedItem = null">×</button>
        </header>
        <pre>{{ selectedItem.content }}</pre>
      </article>
    </div>
  </section>
</template>

<style scoped>
.knowledge-list-wrap {
  min-width: 0;
}

.knowledge-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 13px;
}

.knowledge-toolbar small,
.knowledge-toolbar strong {
  display: block;
}

.knowledge-toolbar small {
  color: #31a5ba;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 1.5px;
}

.knowledge-toolbar strong {
  margin-top: 4px;
  color: #183851;
  font-size: 15px;
}

.knowledge-search {
  width: min(360px, 100%);
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #dce8f0;
  border-radius: 11px;
  padding: 8px 10px;
  color: #7d93a5;
  background: #fff;
}

.knowledge-search input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  color: #2f4a61;
  font-size: 11px;
  background: transparent;
}

.knowledge-search button {
  width: 20px;
  height: 20px;
  border: 0;
  border-radius: 50%;
  background: #f1f5f9;
  color: #7b8fa0;
  line-height: 1;
}

.compact-knowledge-card {
  min-height: 94px;
}

.knowledge-card-main {
  min-width: 0;
}

.knowledge-preview-line {
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.icon-only-btn {
  width: 26px;
  height: 26px;
  display: inline-grid;
  place-items: center;
  padding: 0 !important;
  border: 1px solid #d9e9f3 !important;
  border-radius: 8px !important;
  color: #1677ff !important;
  background: #eef7ff !important;
}

.icon-only-btn:hover {
  color: #0b61d8 !important;
  background: #e2f0ff !important;
}

.knowledge-empty {
  min-height: 260px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  border: 1px solid #e0e9ef;
  border-radius: 14px;
  color: #9aabb9;
  text-align: center;
  background: #fff;
}

.knowledge-empty strong {
  color: #415a70;
  font-size: 13px;
}

.knowledge-empty p {
  margin: 0;
  font-size: 10px;
}

.knowledge-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(15, 30, 45, 0.38);
  backdrop-filter: blur(4px);
}

.knowledge-modal {
  width: min(760px, 100%);
  max-height: min(78vh, 760px);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #dce8f0;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 24px 70px rgba(15, 38, 62, 0.22);
}

.knowledge-modal header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px 14px;
  border-bottom: 1px solid #edf2f6;
}

.knowledge-modal small {
  color: #178b92;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.8px;
}

.knowledge-modal h3 {
  margin: 6px 0 0;
  color: #18324a;
  font-size: 18px;
}

.knowledge-modal header button {
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: 9px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 22px;
  line-height: 1;
}

.knowledge-modal pre {
  margin: 0;
  padding: 18px 22px 22px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: #465f75;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.75;
}
</style>
