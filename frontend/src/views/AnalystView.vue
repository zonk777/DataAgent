<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import ResultChart from '../components/ResultChart.vue'
import ThinkingBlock from '../components/ThinkingBlock.vue'
import TypewriterText from '../components/TypewriterText.vue'
import { api } from '../api'
import type { AnalysisResult, ChatMessage, SessionSummary, ThinkingStep } from '../types'

const props = defineProps<{
  sessions: SessionSummary[]
  chatMessages: ChatMessage[]
  result: AnalysisResult | null
  loading: boolean
  sessionId: string | undefined
  examples: string[]
  thinkingSteps: ThinkingStep[]
  thinkingText: string
  thinkingCollapsed: boolean
}>()

const emit = defineEmits<{
  analyze: [q: string]
  analyzeFile: [file: File, q: string]
  openSession: [id: string]
  deleteSession: [id: string]
  newSession: []
  showResult: [msg: ChatMessage]
  updateSessions: []
  toggleThinking: []
}>()

const question = ref('')
const showSql = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const chosenFile = ref<File | null>(null)

function chooseFile(e: Event) {
  chosenFile.value = (e.target as HTMLInputElement).files?.[0] || null
  if (chosenFile.value) question.value = ''
}
function removeFile() {
  chosenFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

function submitInput() {
  if (props.loading) return
  if (chosenFile.value) {
    const file = chosenFile.value
    const q = question.value || ''
    question.value = ''
    removeFile()
    emit('analyzeFile', file, q)
    return
  }
  if (question.value) emit('analyze', question.value)
}

function isLatestMessage(index: number) {
  return index === props.chatMessages.length - 1
}
</script>

<template>
  <section class="page analyst-page">
    <div class="analyst-layout">
      <div class="conversation-panel">
        <div class="analyst-welcome"><span><AppIcon name="spark" :size="25" /></span><div><h2>数据智能顾问</h2><p>支持数据分析、知识问答与连续追问</p></div><button class="new-chat-btn" @click="emit('newSession')">新对话</button></div>
        <div class="session-history">
          <div class="session-history-title"><small>历史对话</small><span>{{ sessions.length }} 个会话</span></div>
          <div class="session-history-list">
            <div v-for="session in sessions" :key="session.id" :class="['session-history-item', { active: sessionId === session.id }]">
              <button class="session-open-btn" type="button" @click="emit('openSession', session.id)">
                <strong>{{ session.title }}</strong><small>{{ session.message_count }} 条消息 · {{ session.updated_at }}</small>
              </button>
              <button class="session-delete-btn" type="button" title="删除历史对话" @click="emit('deleteSession', session.id)">×</button>
            </div>
          </div>
        </div>
        <div v-if="chatMessages.length" class="conversation-messages">
          <article v-for="(message, index) in chatMessages" :key="message.id || index" :class="['conversation-message', message.role]" @click="emit('showResult', message)">
            <small>{{ message.role === 'user' ? '你' : 'DataAgent' }}</small>
            <TypewriterText v-if="message._streamed" :text="message.content" :enabled="true" />
            <p v-else>{{ message.content }}</p>
            <em v-if="message.payload">查看该轮结果 →</em>
          </article>
        </div>
        <div v-else class="empty-chat"><AppIcon name="spark" :size="24"/><p>开始一次数据分析，或询问指标口径与业务规则。</p></div>
        <ThinkingBlock
          v-if="thinkingSteps.length"
          :steps="thinkingSteps"
          :thinking-text="thinkingText"
          :is-streaming="loading"
          :collapsed="thinkingCollapsed"
          @toggle="emit('toggleThinking')"
        />
        <div v-if="result?.context_applied" class="context-note"><AppIcon name="check" :size="15"/>已继承上一轮的分析条件</div>
        <div class="followups"><small>快捷提问</small><div><button v-for="item in examples" :key="item" @click="emit('analyze', item)">{{ item }}</button></div></div>
        <div :class="['chat-box', { 'has-file': chosenFile }]">
          <div v-if="chosenFile" class="file-chip">
            <AppIcon name="file" :size="14" />
            <span>{{ chosenFile.name }}</span>
            <button class="file-chip-remove" @click="removeFile" title="移除文件">&times;</button>
          </div>
          <div class="chat-input-row">
            <textarea v-model="question" rows="2" placeholder="输入问题，或上传 PDF/Word/MD 文档进行分析..." @keydown.enter.exact.prevent="submitInput"/>
            <div class="chat-actions">
              <input ref="fileInput" type="file" accept=".pdf,.docx,.doc,.md,.txt" @change="chooseFile" hidden />
              <button class="icon-btn" title="上传文档分析" :disabled="loading" @click="fileInput?.click()"><AppIcon name="upload" :size="17" /></button>
              <button :disabled="loading || (!question && !chosenFile)" @click="submitInput"><AppIcon name="send" :size="18" /></button>
            </div>
          </div>
        </div>
      </div>
      <div class="result-panel">
        <div v-if="!result" class="empty-result"><div><AppIcon name="chart" :size="34" /></div><h3>分析结果将在这里呈现</h3><p>选择一个示例问题，或在左侧输入你的业务问题。</p></div>
        <template v-else>
          <div class="report-header"><div><small>{{ result.answer_type === 'knowledge_qa' ? 'KNOWLEDGE ANSWER' : 'ANALYSIS REPORT' }}</small><h2>{{ result.chart.title }}</h2></div><a :href="api.reportUrl(result.session_id)" target="_blank"><AppIcon name="file" :size="17" />导出报告</a></div>
          <div class="result-meta"><span>{{ result.intent }}</span><span>{{ result.execution_mode }}</span><span>{{ result.answer_type === 'knowledge_qa' ? `${result.knowledge_refs.length} 条知识依据` : `${result.rows.length} 条结果` }}</span><span v-if="result.context_applied">已使用对话上下文</span></div>
          <div v-if="result.chart.type !== 'none'" class="chart-card"><ResultChart :result="result" /></div>
          <div class="insight-card"><h3><AppIcon name="spark" :size="19" />{{ result.answer_type === 'knowledge_qa' ? '知识库回答' : '关键发现' }}</h3><div v-for="(insight, index) in result.insights" :key="insight"><span>{{ index + 1 }}</span><p class="answer-text">{{ insight }}</p></div></div>
          <div v-if="result.knowledge_refs.length" class="knowledge-sources"><h3><AppIcon name="book" :size="18"/>知识依据</h3><article v-for="item in result.knowledge_refs" :key="item.id"><div><strong>{{ item.title }}</strong><em>{{ item.retrieval_mode || item.category }}<template v-if="item.score"> · {{ item.score.toFixed(3) }}</template></em></div><p>{{ item.content }}</p></article></div>
          <div v-if="result.rows.length" class="data-table-card"><div class="subhead"><h3>查询结果</h3><button @click="showSql = !showSql">{{ showSql ? '隐藏 SQL' : '查看 SQL' }}</button></div>
            <pre v-if="showSql" class="sql-block">{{ result.sql }}</pre>
            <div class="table-scroll"><table><thead><tr><th v-for="column in result.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, index) in result.rows" :key="index"><td v-for="column in result.columns" :key="column">{{ row[column] }}</td></tr></tbody></table></div>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat-box {
  display: grid;
  grid-template-columns: 1fr;
  align-items: stretch;
  gap: 8px;
  padding: 10px;
}

.chat-input-row {
  min-width: 0;
  display: flex;
  align-items: flex-end;
  gap: 10px;
}

.chat-input-row textarea {
  width: 100%;
  min-width: 0;
  min-height: 48px;
  padding: 10px 6px 8px 10px;
}

.chat-actions {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.file-chip {
  width: fit-content;
  max-width: 100%;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px 7px 10px;
  border: 1px solid #dbe9f2;
  border-radius: 12px;
  background: #f4f9fd;
  color: #244258;
  font-size: 12px;
  box-shadow: 0 4px 12px rgba(38, 77, 108, 0.05);
}

.file-chip span {
  max-width: min(360px, calc(100vw - 420px));
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.chat-box .file-chip-remove {
  width: 24px;
  height: 24px;
  border-radius: 8px;
  background: #e9f2fb;
  color: #527089;
  box-shadow: none;
  font-size: 17px;
  line-height: 1;
}

.chat-box .file-chip-remove:hover {
  color: #c24154;
  background: #fff1f3;
}

.chat-box.has-file {
  padding-top: 12px;
}
</style>
