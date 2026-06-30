<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from './components/AppIcon.vue'
import ResultChart from './components/ResultChart.vue'
import { api } from './api'
import type { AdminUser, AnalysisResult, AuditLog, ChatMessage, ConfigStatus, DashboardData, Dataset, DatasetQuality, KnowledgeItem, SessionSummary, ViewName } from './types'

const activeView = ref<ViewName>('overview')
const dashboard = ref<DashboardData | null>(null)
const datasets = ref<Dataset[]>([])
const config = ref<ConfigStatus | null>(null)
const knowledge = ref<KnowledgeItem[]>([])
const sessions = ref<SessionSummary[]>([])
const chatMessages = ref<ChatMessage[]>([])
const selectedDatasetId = ref<number | undefined>()
const selectedDataset = ref<Dataset | null>(null)
const selectedDatasetQuality = ref<DatasetQuality | null>(null)
const result = ref<AnalysisResult | null>(null)
const question = ref('分析近30天各地区销售额趋势')
const loading = ref(false)
const error = ref('')
const sessionId = ref<string>()
const showSql = ref(false)
const uploadFile = ref<File | null>(null)
const uploadName = ref('')
const uploadDescription = ref('')
const uploading = ref(false)
const datasetEdit = ref({ name: '', description: '' })
const columnDrafts = ref<Record<string, string>>({})
const mysqlForm = ref({ host: '127.0.0.1', port: 3306, username: 'root', password: '', database: '', table: '', name: '', description: '', limit: 100000 })
const importingMysql = ref(false)
const knowledgeForm = ref({ title: '', content: '', category: 'business_rule' })
const editingKnowledgeId = ref<number | null>(null)
const knowledgeFile = ref<File | null>(null)
const knowledgeUploadTitle = ref('')
const uploadingKnowledge = ref(false)
const currentAdmin = ref<AdminUser | null>(null)
const admins = ref<AdminUser[]>([])
const authChecked = ref(false)
const loginForm = ref({ username: '', password: '' })
const loginLoading = ref(false)
const newAdminForm = ref({ username: '', password: '', role: 'admin', dataset_ids: [] as number[] })
const creatingAdmin = ref(false)
const auditLogs = ref<AuditLog[]>([])
const auditFilters = ref({ username: '', action: '', date_from: '', date_to: '' })
const loadingAudit = ref(false)

const navItems: Array<{ id: ViewName; label: string; icon: string }> = [
  { id: 'overview', label: '工作台', icon: 'home' },
  { id: 'analyst', label: '智能分析', icon: 'spark' },
  { id: 'datasets', label: '数据源', icon: 'database' },
  { id: 'knowledge', label: '业务知识库', icon: 'book' },
  { id: 'accounts', label: '账户管理', icon: 'settings' },
  { id: 'audit', label: '审计日志', icon: 'file' },
  { id: 'settings', label: '系统配置', icon: 'settings' },
]

const pageTitle = computed(() => navItems.find((item) => item.id === activeView.value)?.label || 'DataAgent')
const examples = ['统计各地区销售额', '按月份展示销售额趋势', '查询投诉率最高的区域', '分析华东地区转化率']
const roleOptions = [
  { value: 'admin', label: '管理员' },
  { value: 'data_analyst', label: '数据分析人员' },
  { value: 'business_user', label: '业务人员' },
]

function roleLabel(role?: string) {
  if (role === 'initial_admin') return '初始管理员'
  return roleOptions.find((item) => item.value === role)?.label || '管理员'
}

function canManageData() {
  return ['initial_admin', 'admin', 'data_analyst'].includes(currentAdmin.value?.role || '')
}

function auditQuery() {
  const params = new URLSearchParams()
  Object.entries(auditFilters.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  return params.toString() ? `?${params.toString()}` : ''
}

async function loadBase() {
  try {
    const [dashboardData, datasetData, configData, knowledgeData, sessionData] = await Promise.all([
      api.dashboard(), api.datasets(), api.config(), api.knowledge(), api.sessions(),
    ])
    dashboard.value = dashboardData
    datasets.value = datasetData
    config.value = configData
    knowledge.value = knowledgeData
    sessions.value = sessionData
    selectedDatasetId.value ||= datasetData[0]?.id
  } catch (err) {
    error.value = err instanceof Error ? err.message : '后端服务未连接'
  }
}

async function bootstrap() {
  try {
    const me = await api.me()
    currentAdmin.value = me.admin
    await loadBase()
    admins.value = await api.admins()
  } catch {
    currentAdmin.value = null
  } finally {
    authChecked.value = true
  }
}

async function login() {
  if (!loginForm.value.username || !loginForm.value.password) return
  loginLoading.value = true
  error.value = ''
  try {
    const data = await api.login(loginForm.value.username, loginForm.value.password)
    currentAdmin.value = data.admin
    loginForm.value.password = ''
    await loadBase()
    admins.value = await api.admins()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '登录失败'
  } finally {
    loginLoading.value = false
  }
}

async function logout() {
  await api.logout().catch(() => undefined)
  currentAdmin.value = null
  dashboard.value = null
  datasets.value = []
  config.value = null
  knowledge.value = []
  sessions.value = []
  chatMessages.value = []
  result.value = null
  sessionId.value = undefined
  activeView.value = 'overview'
}

async function analyze(nextQuestion?: string) {
  const value = (nextQuestion || question.value).trim()
  if (!value) return
  question.value = value
  loading.value = true
  error.value = ''
  activeView.value = 'analyst'
  chatMessages.value.push({ role: 'user', content: value })
  try {
    result.value = await api.analyze(value, selectedDatasetId.value, sessionId.value)
    sessionId.value = result.value.session_id
    chatMessages.value.push({ role: 'assistant', content: result.value.insights.join('\n'), payload: result.value })
    question.value = ''
    sessions.value = await api.sessions()
    dashboard.value = await api.dashboard()
  } catch (err) {
    chatMessages.value.pop()
    error.value = err instanceof Error ? err.message : '分析失败'
  } finally {
    loading.value = false
  }
}

async function openSession(id: string) {
  loading.value = true
  error.value = ''
  try {
    const detail = await api.session(id)
    sessionId.value = detail.id
    selectedDatasetId.value = detail.dataset_id || selectedDatasetId.value
    chatMessages.value = detail.messages
    const lastResult = [...detail.messages].reverse().find((item) => item.role === 'assistant' && item.payload)?.payload
    result.value = lastResult || null
    question.value = ''
    activeView.value = 'analyst'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '读取历史会话失败'
  } finally {
    loading.value = false
  }
}

function startNewSession() {
  sessionId.value = undefined
  chatMessages.value = []
  result.value = null
  question.value = ''
  activeView.value = 'analyst'
}

async function deleteHistorySession(id: string, event?: MouseEvent) {
  event?.stopPropagation()
  const session = sessions.value.find((item) => item.id === id)
  const title = session?.title || '该历史对话'
  if (!window.confirm(`确定删除「${title}」吗？删除后无法恢复。`)) return

  error.value = ''
  try {
    await api.deleteSession(id)
    sessions.value = sessions.value.filter((item) => item.id !== id)
    if (sessionId.value === id) {
      startNewSession()
    }
    dashboard.value = await api.dashboard()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除历史对话失败'
  }
}

function showMessageResult(message: ChatMessage) {
  if (message.payload) result.value = message.payload
}

async function inspectDataset(id: number) {
  activeView.value = 'datasets'
  selectedDatasetId.value = id
  selectedDataset.value = await api.dataset(id)
  selectedDatasetQuality.value = await api.datasetQuality(id)
  datasetEdit.value = { name: selectedDataset.value.name, description: selectedDataset.value.description }
  columnDrafts.value = Object.fromEntries((selectedDataset.value.columns || []).map((column) => [column.name, column.description]))
}

function chooseFile(event: Event) {
  uploadFile.value = (event.target as HTMLInputElement).files?.[0] || null
  if (uploadFile.value && !uploadName.value) uploadName.value = uploadFile.value.name.replace(/\.[^.]+$/, '')
}

async function upload() {
  if (!uploadFile.value) return
  uploading.value = true
  error.value = ''
  try {
    const created = await api.upload(uploadFile.value, uploadName.value, uploadDescription.value)
    datasets.value = await api.datasets()
    selectedDatasetId.value = created.id
    selectedDataset.value = created
    selectedDatasetQuality.value = await api.datasetQuality(created.id)
    datasetEdit.value = { name: created.name, description: created.description }
    columnDrafts.value = Object.fromEntries((created.columns || []).map((column) => [column.name, column.description]))
    uploadFile.value = null
    uploadName.value = ''
    uploadDescription.value = ''
    dashboard.value = await api.dashboard()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '上传失败'
  } finally {
    uploading.value = false
  }
}

async function saveDatasetMeta() {
  if (!selectedDataset.value) return
  selectedDataset.value = await api.updateDataset(selectedDataset.value.id, datasetEdit.value)
  datasets.value = await api.datasets()
}

async function saveColumnDescription(columnName: string) {
  if (!selectedDataset.value) return
  selectedDataset.value = await api.updateDatasetColumn(selectedDataset.value.id, columnName, columnDrafts.value[columnName] || '')
}

async function deleteSelectedDataset() {
  if (!selectedDataset.value) return
  if (!window.confirm(`确定删除数据源「${selectedDataset.value.name}」吗？相关知识片段和分析权限也会同步失效。`)) return
  await api.deleteDataset(selectedDataset.value.id)
  datasets.value = await api.datasets()
  selectedDataset.value = null
  selectedDatasetQuality.value = null
  selectedDatasetId.value = datasets.value[0]?.id
  dashboard.value = await api.dashboard()
}

async function importMysql() {
  if (!mysqlForm.value.host || !mysqlForm.value.database || !mysqlForm.value.table || !mysqlForm.value.username) return
  importingMysql.value = true
  error.value = ''
  try {
    const created = await api.importMysql(mysqlForm.value)
    datasets.value = await api.datasets()
    selectedDatasetId.value = created.id
    await inspectDataset(created.id)
    mysqlForm.value = { host: '127.0.0.1', port: 3306, username: 'root', password: '', database: '', table: '', name: '', description: '', limit: 100000 }
    dashboard.value = await api.dashboard()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'MySQL 导入失败'
  } finally {
    importingMysql.value = false
  }
}

function chooseKnowledgeFile(event: Event) {
  knowledgeFile.value = (event.target as HTMLInputElement).files?.[0] || null
}

async function uploadKnowledgeDocument() {
  if (!knowledgeFile.value) return
  uploadingKnowledge.value = true
  error.value = ''
  try {
    await api.uploadKnowledge(knowledgeFile.value, knowledgeUploadTitle.value, knowledgeForm.value.category, selectedDatasetId.value)
    knowledge.value = await api.knowledge()
    config.value = await api.config()
    dashboard.value = await api.dashboard()
    knowledgeFile.value = null
    knowledgeUploadTitle.value = ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : '上传知识文档失败'
  } finally {
    uploadingKnowledge.value = false
  }
}

async function addKnowledge() {
  if (!knowledgeForm.value.title || !knowledgeForm.value.content) return
  if (editingKnowledgeId.value) {
    await api.updateKnowledge(editingKnowledgeId.value, { ...knowledgeForm.value, dataset_id: selectedDatasetId.value })
  } else {
    await api.createKnowledge({ ...knowledgeForm.value, dataset_id: selectedDatasetId.value })
  }
  knowledge.value = await api.knowledge()
  dashboard.value = await api.dashboard()
  config.value = await api.config()
  knowledgeForm.value = { title: '', content: '', category: 'business_rule' }
  editingKnowledgeId.value = null
}

function editKnowledgeItem(item: KnowledgeItem) {
  editingKnowledgeId.value = item.id
  selectedDatasetId.value = item.dataset_id || selectedDatasetId.value
  knowledgeForm.value = { title: item.title, content: item.content, category: item.category }
}

function cancelKnowledgeEdit() {
  editingKnowledgeId.value = null
  knowledgeForm.value = { title: '', content: '', category: 'business_rule' }
}

async function reindexKnowledge() {
  await api.reindexKnowledge()
  config.value = await api.config()
}

async function deleteKnowledgeItem(item: KnowledgeItem) {
  if (!window.confirm(`确定删除知识片段「${item.title}」吗？删除后知识库问答将不再引用它。`)) return
  error.value = ''
  try {
    await api.deleteKnowledge(item.id)
    knowledge.value = knowledge.value.filter((entry) => entry.id !== item.id)
    dashboard.value = await api.dashboard()
    config.value = await api.config()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除知识片段失败'
  }
}

async function addAdmin() {
  if (!newAdminForm.value.username || !newAdminForm.value.password) return
  creatingAdmin.value = true
  error.value = ''
  try {
    await api.createAdmin(newAdminForm.value)
    newAdminForm.value = { username: '', password: '', role: 'admin', dataset_ids: [] }
    admins.value = await api.admins()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '新增管理员失败'
  } finally {
    creatingAdmin.value = false
  }
}

async function saveAdminPermission(admin: AdminUser) {
  await api.updateAdmin(admin.id, { role: admin.role, dataset_ids: admin.dataset_permissions || [] })
  admins.value = await api.admins()
}

async function deleteAdminAccount(admin: AdminUser) {
  if (!window.confirm(`确定删除账号「${admin.username}」吗？`)) return
  await api.deleteAdmin(admin.id)
  admins.value = await api.admins()
}

async function loadAuditLogs() {
  loadingAudit.value = true
  error.value = ''
  try {
    auditLogs.value = await api.auditLogs(auditQuery())
  } catch (err) {
    error.value = err instanceof Error ? err.message : '读取审计日志失败'
  } finally {
    loadingAudit.value = false
  }
}

watch(activeView, (view) => {
  if (view === 'audit' && !auditLogs.value.length) loadAuditLogs()
})

onMounted(bootstrap)
</script>

<template>
  <div v-if="!authChecked" class="auth-screen">
    <div class="auth-card"><div class="brand-mark"><AppIcon name="chart" :size="28" /></div><h1>DataAgent</h1><p>正在检查登录状态...</p></div>
  </div>

  <div v-else-if="!currentAdmin" class="auth-screen">
    <form class="auth-card login-card" @submit.prevent="login">
      <div class="brand-mark"><AppIcon name="chart" :size="28" /></div>
      <h1>数据智能体服务系统</h1>
      <p>请使用管理员账号登录后继续访问系统。</p>
      <label>账号<input v-model="loginForm.username" autocomplete="username" placeholder="请输入账号" /></label>
      <label>密码<input v-model="loginForm.password" autocomplete="current-password" placeholder="请输入密码" type="password" /></label>
      <button class="primary-btn" :disabled="loginLoading">{{ loginLoading ? '登录中...' : '登录' }}</button>
      <div v-if="error" class="auth-error">{{ error }}</div>
    </form>
  </div>

  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark"><AppIcon name="chart" :size="24" /></div>
        <div><strong>DataAgent</strong><small>企业数据智能体</small></div>
      </div>
      <nav>
        <button v-for="item in navItems" :key="item.id" :class="['nav-item', { active: activeView === item.id }]" @click="activeView = item.id">
          <AppIcon :name="item.icon" /><span>{{ item.label }}</span>
        </button>
      </nav>
      <div class="sidebar-foot">
        <div class="status-dot" :class="{ online: !error }" />
        <div><strong>{{ error ? '服务待连接' : '服务运行正常' }}</strong><small>{{ config?.llm_configured ? config.llm_model : '本地演示模式' }}</small></div>
      </div>
    </aside>

    <main class="main-area">
      <header class="topbar">
        <div><p>DATA INTELLIGENCE</p><h1>{{ pageTitle }}</h1></div>
        <div class="top-actions">
          <select v-model="selectedDatasetId" aria-label="选择数据集">
            <option v-for="dataset in datasets" :key="dataset.id" :value="dataset.id">{{ dataset.name }}</option>
          </select>
          <button class="account-chip" @click="activeView = 'accounts'">{{ currentAdmin?.username }}<span>{{ currentAdmin?.is_initial_admin ? '初始管理员' : '普通管理员' }}</span></button>
          <button class="logout-btn" @click="logout">退出</button>
        </div>
      </header>

      <div v-if="error" class="error-banner">{{ error }} <button @click="loadBase">重新连接</button></div>

      <section v-if="activeView === 'overview'" class="page overview-page">
        <div class="hero-card">
          <div class="hero-copy">
            <span class="eyebrow"><AppIcon name="spark" :size="16" /> AI 数据分析助手</span>
            <h2>把业务问题，直接变成<br><em>可信的数据结论</em></h2>
            <p>自然语言提问，自动完成数据理解、SQL 生成、安全执行、图表展示和分析报告。</p>
            <div class="hero-input">
              <input v-model="question" @keyup.enter="analyze()" placeholder="例如：分析本季度各区域销售额变化原因" />
              <button @click="analyze()"><AppIcon name="send" :size="18" />开始分析</button>
            </div>
            <div class="example-row"><span>试试：</span><button v-for="item in examples.slice(0, 3)" :key="item" @click="analyze(item)">{{ item }}</button></div>
          </div>
          <div class="hero-visual">
            <div class="orb orb-one"/><div class="orb orb-two"/>
            <div class="mini-report">
              <div class="mini-head"><span><AppIcon name="chart" :size="18" />经营指标概览</span><i>实时</i></div>
              <div class="mini-bars"><span style="height:42%"/><span style="height:66%"/><span style="height:55%"/><span style="height:82%"/><span style="height:72%"/><span style="height:94%"/><span style="height:78%"/></div>
              <div class="mini-stat"><small>本月销售额</small><strong>¥ 2,359,899</strong><em>↗ 12.6%</em></div>
            </div>
          </div>
        </div>

        <div class="metric-grid">
          <article><span class="metric-icon blue"><AppIcon name="database" /></span><div><small>已接入数据集</small><strong>{{ dashboard?.dataset_count ?? '—' }}</strong></div><em>个</em></article>
          <article><span class="metric-icon cyan"><AppIcon name="book" /></span><div><small>业务知识片段</small><strong>{{ dashboard?.knowledge_count ?? '—' }}</strong></div><em>条</em></article>
          <article><span class="metric-icon violet"><AppIcon name="spark" /></span><div><small>累计智能分析</small><strong>{{ dashboard?.analysis_count ?? '—' }}</strong></div><em>次</em></article>
          <article><span class="metric-icon green"><AppIcon name="chart" /></span><div><small>分析会话</small><strong>{{ dashboard?.session_count ?? '—' }}</strong></div><em>个</em></article>
        </div>

        <div class="content-grid">
          <article class="panel quick-panel"><div class="panel-title"><div><small>QUICK START</small><h3>常用分析场景</h3></div></div>
            <button v-for="(item, index) in examples" :key="item" @click="analyze(item)"><span>{{ index + 1 }}</span><div><strong>{{ item }}</strong><small>{{ index % 2 ? '趋势对比与可视化' : '指标查询与维度拆解' }}</small></div><b>→</b></button>
          </article>
          <article class="panel data-panel"><div class="panel-title"><div><small>DATA ASSETS</small><h3>数据资产</h3></div><button @click="activeView = 'datasets'">管理数据源</button></div>
            <div v-for="dataset in datasets.slice(0, 4)" :key="dataset.id" class="dataset-line" @click="inspectDataset(dataset.id)">
              <span><AppIcon name="database" /></span><div><strong>{{ dataset.name }}</strong><small>{{ dataset.row_count.toLocaleString() }} 行 · {{ dataset.column_count }} 个字段</small></div><i>{{ dataset.source_type.toUpperCase() }}</i>
            </div>
          </article>
        </div>
      </section>

      <section v-else-if="activeView === 'analyst'" class="page analyst-page">
        <div class="analyst-layout">
          <div class="conversation-panel">
            <div class="analyst-welcome"><span><AppIcon name="spark" :size="25" /></span><div><h2>数据智能顾问</h2><p>支持数据分析、知识问答与连续追问</p></div><button class="new-chat-btn" @click="startNewSession">新对话</button></div>
            <div class="session-history">
              <div class="session-history-title"><small>历史对话</small><span>{{ sessions.length }} 个会话</span></div>
              <div class="session-history-list">
                <div v-for="session in sessions" :key="session.id" :class="['session-history-item', { active: sessionId === session.id }]">
                  <button class="session-open-btn" type="button" @click="openSession(session.id)">
                    <strong>{{ session.title }}</strong><small>{{ session.message_count }} 条消息 · {{ session.updated_at }}</small>
                  </button>
                  <button class="session-delete-btn" type="button" title="删除历史对话" @click="deleteHistorySession(session.id, $event)">×</button>
                </div>
              </div>
            </div>
            <div v-if="chatMessages.length" class="conversation-messages">
              <article v-for="(message, index) in chatMessages" :key="message.id || index" :class="['conversation-message', message.role]" @click="showMessageResult(message)">
                <small>{{ message.role === 'user' ? '你' : 'DataAgent' }}</small>
                <p>{{ message.content }}</p>
                <em v-if="message.payload">查看该轮结果 →</em>
              </article>
            </div>
            <div v-else class="empty-chat"><AppIcon name="spark" :size="24"/><p>开始一次数据分析，或询问指标口径与业务规则。</p></div>
            <div v-if="loading" class="thinking"><i/><i/><i/><span>正在结合上下文进行分析...</span></div>
            <div v-if="result?.context_applied" class="context-note"><AppIcon name="check" :size="15"/>已继承上一轮的分析条件</div>
            <div class="followups"><small>快捷提问</small><div><button v-for="item in examples" :key="item" @click="analyze(item)">{{ item }}</button></div></div>
            <div class="chat-box"><textarea v-model="question" rows="2" placeholder="可追问：只看华东；按产品拆分；或询问投诉率如何计算" @keydown.enter.exact.prevent="analyze()"/><button :disabled="loading" @click="analyze()"><AppIcon name="send" :size="18" /></button></div>
          </div>

          <div class="result-panel">
            <div v-if="!result" class="empty-result"><div><AppIcon name="chart" :size="34" /></div><h3>分析结果将在这里呈现</h3><p>选择一个示例问题，或在左侧输入你的业务问题。</p></div>
            <template v-else>
              <div class="report-header">
                <div><small>{{ result.answer_type === 'knowledge_qa' ? 'KNOWLEDGE ANSWER' : 'ANALYSIS REPORT' }}</small><h2>{{ result.chart.title }}</h2></div>
                <div class="report-actions">
                  <a :href="api.reportUrl(result.session_id, 'html')" target="_blank"><AppIcon name="file" :size="17" />HTML</a>
                  <a :href="api.reportUrl(result.session_id, 'docx')" download><AppIcon name="file" :size="17" />Word</a>
                  <a :href="api.reportUrl(result.session_id, 'pdf')" download><AppIcon name="file" :size="17" />PDF</a>
                  <a :href="api.reportUrl(result.session_id, 'md')" download><AppIcon name="file" :size="17" />Markdown</a>
                </div>
              </div>
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

      <section v-else-if="activeView === 'datasets'" class="page">
        <div class="page-intro"><div><span class="eyebrow"><AppIcon name="database" :size="16" /> DATA CATALOG</span><h2>数据源与元数据</h2><p>支持 CSV / Excel / MySQL 接入，自动识别字段、预览样例并生成数据质量检查。</p></div></div>
        <div class="dataset-layout">
          <article class="panel upload-panel">
            <h3><AppIcon name="upload" />导入数据文件</h3>
            <label class="drop-zone"><input type="file" accept=".csv,.xls,.xlsx" @change="chooseFile"/><AppIcon name="upload" :size="32"/><strong>{{ uploadFile?.name || '选择 CSV / Excel 文件' }}</strong><small>单文件最大 100MB</small></label>
            <input v-model="uploadName" placeholder="数据集名称（可选）"/>
            <textarea v-model="uploadDescription" placeholder="数据集用途与说明" rows="3"/>
            <button class="primary-btn" :disabled="!uploadFile || uploading || !canManageData()" @click="upload">{{ uploading ? '正在导入...' : '开始导入' }}</button>
          </article>
          <article class="panel upload-panel">
            <h3><AppIcon name="database" />导入 MySQL 表</h3>
            <input v-model="mysqlForm.host" placeholder="主机地址，如 127.0.0.1"/>
            <input v-model.number="mysqlForm.port" type="number" placeholder="端口"/>
            <input v-model="mysqlForm.username" placeholder="用户名"/>
            <input v-model="mysqlForm.password" type="password" placeholder="密码"/>
            <input v-model="mysqlForm.database" placeholder="数据库名"/>
            <input v-model="mysqlForm.table" placeholder="表名"/>
            <input v-model="mysqlForm.name" placeholder="导入后的数据集名称（可选）"/>
            <button class="primary-btn" :disabled="importingMysql || !canManageData()" @click="importMysql">{{ importingMysql ? '正在导入...' : '连接并导入' }}</button>
          </article>
          <article class="panel"><div class="panel-title"><div><small>CONNECTED</small><h3>已接入数据集</h3></div></div><div class="dataset-cards"><button v-for="dataset in datasets" :key="dataset.id" :class="{ selected: selectedDatasetId === dataset.id }" @click="inspectDataset(dataset.id)"><span><AppIcon name="database" /></span><div><strong>{{ dataset.name }}</strong><small>{{ dataset.description || '暂无描述' }}</small><em>{{ dataset.row_count.toLocaleString() }} 行 · {{ dataset.column_count }} 字段</em></div><i>{{ dataset.source_type }}</i></button></div></article>
        </div>
        <article v-if="selectedDataset" class="panel metadata-panel">
          <div class="panel-title">
            <div><small>METADATA</small><h3>{{ selectedDataset.name }} · 字段说明</h3></div>
            <button v-if="canManageData()" class="danger-lite" @click="deleteSelectedDataset">删除数据源</button>
          </div>
          <div class="meta-edit-row">
            <input v-model="datasetEdit.name" placeholder="数据集名称"/>
            <input v-model="datasetEdit.description" placeholder="数据集说明"/>
            <button @click="saveDatasetMeta">保存元数据</button>
          </div>
          <div v-if="selectedDatasetQuality" class="quality-grid">
            <div v-for="item in selectedDatasetQuality.summary" :key="item">{{ item }}</div>
          </div>
          <div class="table-scroll"><table><thead><tr><th>字段</th><th>类型</th><th>业务说明</th><th>样例值</th><th>缺失率</th><th>操作</th></tr></thead><tbody><tr v-for="column in selectedDataset.columns" :key="column.name"><td><code>{{ column.name }}</code></td><td>{{ column.data_type }}</td><td><input v-model="columnDrafts[column.name]" class="inline-input"/></td><td>{{ column.sample_value }}</td><td>{{ (column.null_rate * 100).toFixed(1) }}%</td><td><button @click="saveColumnDescription(column.name)">保存</button></td></tr></tbody></table></div>
          <div v-if="selectedDataset.preview?.length" class="preview-block"><h3>前 100 行样例数据</h3><div class="table-scroll"><table><thead><tr><th v-for="column in selectedDataset.columns" :key="column.name">{{ column.name }}</th></tr></thead><tbody><tr v-for="(row, index) in selectedDataset.preview.slice(0, 100)" :key="index"><td v-for="column in selectedDataset.columns" :key="column.name">{{ row[column.name] }}</td></tr></tbody></table></div></div>
        </article>
      </section>

      <section v-else-if="activeView === 'knowledge'" class="page">
        <div class="page-intro"><div><span class="eyebrow"><AppIcon name="book" :size="16" /> BUSINESS KNOWLEDGE</span><h2>指标口径与业务知识</h2><p>用于 RAG 检索，让智能体理解企业专有字段、指标和规则。</p></div></div>
        <div class="knowledge-layout">
          <article class="panel knowledge-form">
            <h3>{{ editingKnowledgeId ? '编辑知识片段' : '新增知识片段' }}</h3>
            <input v-model="knowledgeForm.title" placeholder="标题，如：销售额口径"/>
            <select v-model="knowledgeForm.category"><option value="metric">指标口径</option><option value="business_rule">业务规则</option><option value="data_dictionary">数据字典</option><option value="example">历史问答</option></select>
            <textarea v-model="knowledgeForm.content" rows="7" placeholder="输入详细定义、适用范围和计算规则"/>
            <button class="primary-btn" :disabled="!canManageData()" @click="addKnowledge">{{ editingKnowledgeId ? '保存修改并重建索引' : '保存并加入索引' }}</button>
            <button v-if="editingKnowledgeId" class="secondary-btn" @click="cancelKnowledgeEdit">取消编辑</button>
            <div class="knowledge-upload-box">
              <h3>上传业务文档</h3>
              <input type="file" accept=".docx,.pdf,.md,.markdown,.txt" @change="chooseKnowledgeFile"/>
              <input v-model="knowledgeUploadTitle" placeholder="文档标题（可选）"/>
              <button class="primary-btn" :disabled="!knowledgeFile || uploadingKnowledge || !canManageData()" @click="uploadKnowledgeDocument">{{ uploadingKnowledge ? '正在切片...' : '上传并自动切片' }}</button>
              <button class="secondary-btn" :disabled="!canManageData()" @click="reindexKnowledge">重建向量索引</button>
            </div>
          </article>
          <div class="knowledge-list"><article v-for="item in knowledge" :key="item.id" class="knowledge-card"><span><AppIcon name="book" /></span><div><div class="knowledge-card-head"><strong>{{ item.title }}</strong><div><em>{{ item.category }}</em><button type="button" @click="editKnowledgeItem(item)">编辑</button><button type="button" @click="deleteKnowledgeItem(item)">删除</button></div></div><p>{{ item.content }}</p></div></article></div>
        </div>
      </section>

      <section v-else-if="activeView === 'accounts'" class="page">
        <div class="page-intro"><div><span class="eyebrow"><AppIcon name="settings" :size="16" /> ACCOUNT MANAGEMENT</span><h2>账户与权限管理</h2><p>初始管理员可以创建用户、分配角色，并限制可访问的数据源。</p></div></div>
        <div class="account-layout">
          <article class="panel account-form">
            <h3>加入新用户</h3>
            <template v-if="currentAdmin?.is_initial_admin">
              <input v-model="newAdminForm.username" placeholder="账号"/>
              <input v-model="newAdminForm.password" type="password" placeholder="密码，至少 6 位"/>
              <select v-model="newAdminForm.role"><option v-for="role in roleOptions" :key="role.value" :value="role.value">{{ role.label }}</option></select>
              <select v-model="newAdminForm.dataset_ids" multiple size="4"><option v-for="dataset in datasets" :key="dataset.id" :value="dataset.id">{{ dataset.name }}</option></select>
              <small class="field-help">不选择数据源时，管理员/数据分析人员默认可访问全部数据源；业务人员建议明确授权。</small>
              <button class="primary-btn" :disabled="creatingAdmin" @click="addAdmin">{{ creatingAdmin ? '正在创建...' : '新增用户' }}</button>
            </template>
            <div v-else class="permission-note"><AppIcon name="check" :size="16"/>当前账号无权限新增或修改其他用户。</div>
          </article>
          <article class="panel">
            <div class="panel-title"><div><small>USERS</small><h3>账号列表</h3></div></div>
            <div class="table-scroll"><table><thead><tr><th>ID</th><th>账号</th><th>角色</th><th>授权数据源</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="admin in admins" :key="admin.id"><td>{{ admin.id }}</td><td>{{ admin.username }}</td><td><select v-model="admin.role" :disabled="admin.is_initial_admin || !currentAdmin?.is_initial_admin"><option value="initial_admin" disabled>初始管理员</option><option v-for="role in roleOptions" :key="role.value" :value="role.value">{{ role.label }}</option></select></td><td><select v-model="admin.dataset_permissions" multiple size="3" :disabled="admin.is_initial_admin || !currentAdmin?.is_initial_admin"><option v-for="dataset in datasets" :key="dataset.id" :value="dataset.id">{{ dataset.name }}</option></select></td><td>{{ admin.created_at }}</td><td><button :disabled="admin.is_initial_admin || !currentAdmin?.is_initial_admin" @click="saveAdminPermission(admin)">保存</button><button class="danger-lite" :disabled="admin.is_initial_admin || !currentAdmin?.is_initial_admin" @click="deleteAdminAccount(admin)">删除</button></td></tr></tbody></table></div>
          </article>
        </div>
      </section>

      <section v-else-if="activeView === 'audit'" class="page">
        <div class="page-intro"><div><span class="eyebrow"><AppIcon name="file" :size="16" /> AUDIT LOG</span><h2>审计日志</h2><p>记录登录、数据源、知识库、分析、报告导出和权限变更等关键操作。</p></div></div>
        <article class="panel">
          <div class="audit-filter-row">
            <input v-model="auditFilters.username" placeholder="用户名"/>
            <input v-model="auditFilters.action" placeholder="操作类型，如 export_report"/>
            <input v-model="auditFilters.date_from" type="date"/>
            <input v-model="auditFilters.date_to" type="date"/>
            <button @click="loadAuditLogs">{{ loadingAudit ? '查询中...' : '查询' }}</button>
            <a class="download-link" :href="api.auditExportUrl(auditQuery())" download>导出 Excel</a>
          </div>
          <div class="table-scroll"><table><thead><tr><th>ID</th><th>用户</th><th>操作</th><th>资源</th><th>详情</th><th>状态</th><th>时间</th></tr></thead><tbody><tr v-for="log in auditLogs" :key="log.id"><td>{{ log.id }}</td><td>{{ log.username || '-' }}</td><td>{{ log.action }}</td><td>{{ log.resource_type }}<template v-if="log.resource_id"> / {{ log.resource_id }}</template></td><td>{{ log.detail }}</td><td>{{ log.status }}</td><td>{{ log.created_at }}</td></tr></tbody></table></div>
        </article>
      </section>

      <section v-else class="page">
        <div class="page-intro"><div><span class="eyebrow"><AppIcon name="settings" :size="16" /> SYSTEM SETTINGS</span><h2>模型与基础设施</h2><p>密钥仅从后端环境变量读取，不会返回给浏览器。</p></div></div>
        <div class="settings-grid">
          <article class="panel setting-card"><div class="setting-head"><span class="metric-icon blue"><AppIcon name="spark" /></span><div><h3>大语言模型</h3><p>OpenAI 兼容接口</p></div><em :class="{ ready: config?.llm_configured }">{{ config?.llm_configured ? '已配置' : '待配置' }}</em></div><dl><div><dt>模型</dt><dd>{{ config?.llm_model || '未设置' }}</dd></div><div><dt>API Key</dt><dd>仅后端可见</dd></div></dl></article>
          <article class="panel setting-card"><div class="setting-head"><span class="metric-icon cyan"><AppIcon name="book" /></span><div><h3>Embedding / RAG</h3><p>语义向量检索</p></div><em :class="{ ready: config?.embedding_configured }">{{ config?.embedding_configured ? '已启用' : '关键词降级' }}</em></div><dl><div><dt>Embedding 模型</dt><dd>{{ config?.embedding_model || '未配置' }}</dd></div><div><dt>向量存储</dt><dd>{{ config?.vector_store }}</dd></div><div><dt>已索引知识</dt><dd>{{ config?.vector_indexed_count ?? 0 }} 条</dd></div></dl></article>
        </div>
      </section>
    </main>
  </div>
</template>
