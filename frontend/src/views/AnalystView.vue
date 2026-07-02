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
            <textarea v-model="question" rows="2" placeholder="输入问题，或上传 PDF/Word/Excel/CSV/PPT/MD/TXT 等文件进行分析..." @keydown.enter.exact.prevent="submitInput"/>
            <div class="chat-actions">
              <input ref="fileInput" type="file" accept=".pdf,.docx,.doc,.xlsx,.xls,.csv,.tsv,.pptx,.md,.markdown,.txt,.json,.jsonl,.html,.htm,.xml,.log" @change="chooseFile" hidden />
              <button class="icon-btn" title="上传文件分析" :disabled="loading" @click="fileInput?.click()"><AppIcon name="upload" :size="17" /></button>
              <button :disabled="loading || (!question && !chosenFile)" @click="submitInput"><AppIcon name="send" :size="18" /></button>
            </div>
          </div>
        </div>
      </div>
      <div class="result-panel">
        <div v-if="loading" class="analysis-loading-card">
          <div class="orbital-loader">
            <span></span>
            <i></i>
          </div>
          <div>
            <small>DATAAGENT REASONING</small>
            <h3>智能体正在解析与推理</h3>
            <p>正在读取文件、理解问题并组织分析结论，请稍等片刻。</p>
          </div>
        </div>
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
.analyst-page {
  background:
    radial-gradient(circle at 12% 8%, rgba(55, 128, 255, 0.12), transparent 26%),
    radial-gradient(circle at 88% 18%, rgba(18, 184, 190, 0.12), transparent 28%),
    linear-gradient(135deg, #f7fbff 0%, #eef7fb 48%, #f8fbff 100%);
}

.analyst-layout {
  backdrop-filter: blur(18px);
}

.conversation-panel {
  position: relative;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(247, 252, 255, 0.86)),
    radial-gradient(circle at 0 0, rgba(22, 119, 255, 0.08), transparent 36%);
  border-right: 1px solid rgba(198, 219, 233, 0.8);
}

.conversation-panel::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(64, 152, 203, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(64, 152, 203, 0.04) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: linear-gradient(180deg, #000 0%, transparent 88%);
}

.analyst-welcome,
.session-history,
.chat-box,
.conversation-message,
.context-note {
  position: relative;
  z-index: 1;
}

.analyst-welcome {
  padding: 16px;
  border: 1px solid rgba(213, 230, 242, 0.92);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.76);
  box-shadow: 0 18px 45px rgba(41, 85, 122, 0.08);
}

.analyst-welcome > span {
  box-shadow: 0 12px 28px rgba(31, 130, 231, 0.28);
}

.new-chat-btn {
  border: 0;
  background: linear-gradient(135deg, #177cff, #19bdc7);
  color: white;
  box-shadow: 0 10px 22px rgba(24, 132, 219, 0.24);
}

.session-history {
  background: rgba(255, 255, 255, 0.72);
  border-color: rgba(211, 228, 240, 0.9);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85), 0 12px 28px rgba(55, 93, 124, 0.06);
}

.session-history-item {
  background: rgba(255, 255, 255, 0.86);
  border-color: rgba(218, 232, 241, 0.95);
  box-shadow: 0 6px 18px rgba(48, 86, 114, 0.05);
}

.session-history-item.active {
  background: linear-gradient(135deg, rgba(236, 247, 255, 0.96), rgba(234, 253, 250, 0.96));
  box-shadow: 0 12px 26px rgba(42, 136, 223, 0.14);
}

.conversation-messages {
  position: relative;
  z-index: 1;
}

.conversation-message {
  border-radius: 18px;
  border-color: rgba(217, 231, 241, 0.96);
  box-shadow: 0 14px 35px rgba(31, 71, 105, 0.08);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.conversation-message:hover {
  transform: translateY(-1px);
  box-shadow: 0 18px 42px rgba(31, 71, 105, 0.12);
}

.conversation-message.user {
  background: linear-gradient(135deg, #eaf4ff, #edfaff);
}

.conversation-message.assistant {
  background: rgba(255, 255, 255, 0.92);
}

.result-panel {
  position: relative;
  background:
    radial-gradient(circle at 18% 8%, rgba(74, 149, 247, 0.12), transparent 28%),
    radial-gradient(circle at 90% 0%, rgba(18, 184, 190, 0.13), transparent 25%),
    linear-gradient(180deg, #f4f9fc 0%, #eef5f9 100%);
}

.result-panel::before {
  content: "";
  position: fixed;
  inset: 84px 0 0 38%;
  pointer-events: none;
  background:
    linear-gradient(120deg, transparent 0%, rgba(255,255,255,.32) 34%, transparent 62%);
  opacity: .42;
}

.report-header,
.result-meta,
.chart-card,
.insight-card,
.knowledge-sources,
.data-table-card,
.empty-result,
.analysis-loading-card {
  position: relative;
  z-index: 1;
}

.report-header {
  padding: 18px 20px;
  border: 1px solid rgba(211, 227, 239, 0.95);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 18px 44px rgba(42, 80, 110, 0.08);
}

.report-header a {
  text-decoration: none;
  color: white;
  background: linear-gradient(135deg, #177cff, #19b9c6);
  padding: 11px 15px;
  border-radius: 13px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 12px 24px rgba(24, 132, 219, 0.25);
}

.chart-card,
.insight-card,
.knowledge-sources,
.data-table-card {
  border-radius: 24px;
  border-color: rgba(211, 227, 239, 0.9);
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 0 22px 52px rgba(45, 82, 112, 0.08);
  backdrop-filter: blur(14px);
}

.insight-card > div {
  border-top-color: rgba(226, 236, 243, 0.9);
}

.insight-card > div span {
  background: linear-gradient(135deg, #e7fbf5, #eaf4ff);
  box-shadow: inset 0 0 0 1px rgba(28, 174, 154, 0.1);
}

.empty-result {
  min-height: calc(100vh - 170px);
  border: 1px dashed rgba(164, 198, 220, 0.72);
  border-radius: 28px;
  background:
    linear-gradient(180deg, rgba(255,255,255,.76), rgba(247,252,255,.82)),
    radial-gradient(circle at center, rgba(32, 155, 205, 0.08), transparent 32%);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.9), 0 22px 50px rgba(50, 85, 112, 0.06);
}

.empty-result div {
  background: linear-gradient(135deg, #e7f4ff, #dcfbf7);
  box-shadow: 0 16px 35px rgba(47, 142, 206, 0.16);
}

.analysis-loading-card {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: 18px;
  padding: 18px 20px;
  border: 1px solid rgba(186, 220, 241, 0.92);
  border-radius: 24px;
  background:
    linear-gradient(135deg, rgba(255,255,255,.92), rgba(235,249,253,.9)),
    radial-gradient(circle at 12% 50%, rgba(21, 125, 255, .12), transparent 34%);
  box-shadow: 0 24px 60px rgba(29, 91, 136, 0.13);
}

.analysis-loading-card small {
  color: #26a3b6;
  font-size: 9px;
  letter-spacing: 1.8px;
  font-weight: 900;
}

.analysis-loading-card h3 {
  margin: 5px 0 5px;
  color: #173853;
  font-size: 17px;
}

.analysis-loading-card p {
  margin: 0;
  color: #688195;
  font-size: 11px;
}

.orbital-loader {
  width: 62px;
  height: 62px;
  border-radius: 50%;
  position: relative;
  display: grid;
  place-items: center;
  background: conic-gradient(from 0deg, #1979ff, #17c4c7, #dff9ff, #1979ff);
  animation: spin-orbit 1.05s linear infinite;
  box-shadow: 0 13px 30px rgba(24, 132, 219, 0.28);
}

.orbital-loader::before {
  content: "";
  position: absolute;
  inset: 7px;
  border-radius: inherit;
  background: #f8fdff;
}

.orbital-loader span {
  position: relative;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: linear-gradient(135deg, #177cff, #14bdc4);
  box-shadow: 0 0 18px rgba(20, 171, 219, 0.45);
}

.orbital-loader i {
  position: absolute;
  top: 4px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: white;
  box-shadow: 0 0 16px rgba(255,255,255,.9);
}

@keyframes spin-orbit {
  to { transform: rotate(360deg); }
}

:deep(.thinking-block) {
  border: 1px solid rgba(186, 220, 241, 0.95);
  border-radius: 20px;
  background: rgba(255,255,255,.82);
  box-shadow: 0 18px 38px rgba(36, 82, 116, 0.09);
  backdrop-filter: blur(12px);
}

:deep(.thinking-block.streaming) {
  background:
    linear-gradient(135deg, rgba(255,255,255,.94), rgba(235,249,253,.92)),
    radial-gradient(circle at 8% 20%, rgba(24,132,219,.13), transparent 32%);
}

:deep(.thinking-ring) {
  position: relative;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: conic-gradient(#1a7cff, #18c0c8, #dcefff, #1a7cff);
  box-shadow: 0 8px 20px rgba(28, 135, 219, .22);
}

:deep(.thinking-ring::before) {
  content: "";
  position: absolute;
  inset: 5px;
  border-radius: inherit;
  background: white;
}

:deep(.thinking-ring span) {
  position: relative;
  color: #1674d4;
  font-size: 10px;
  font-weight: 900;
}

:deep(.thinking-ring.spinning) {
  animation: spin-orbit .95s linear infinite;
}

:deep(.thinking-ring.spinning span) {
  animation: counter-spin .95s linear infinite;
}

@keyframes counter-spin {
  to { transform: rotate(-360deg); }
}

:deep(.thinking-block-header .arrow) {
  width: auto;
  padding: 4px 8px;
  border-radius: 999px;
  background: #eef7fc;
  color: #5d7f94;
  font-size: 9px;
}

:deep(.thinking-step) {
  border-radius: 12px;
}

.chat-box {
  display: grid;
  grid-template-columns: 1fr;
  align-items: stretch;
  gap: 8px;
  padding: 10px;
  border-radius: 24px;
  border: 1px solid rgba(186, 213, 231, 0.96);
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 24px 55px rgba(34, 78, 112, 0.12);
  backdrop-filter: blur(16px);
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
  padding: 12px 8px 10px 12px;
  color: #25445e;
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
  border-radius: 16px;
  background: linear-gradient(135deg, #f4f9fd, #eefbfb);
  color: #244258;
  font-size: 12px;
  box-shadow: 0 10px 22px rgba(38, 77, 108, 0.08);
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
