<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from './components/AppIcon.vue'
import ResultChart from './components/ResultChart.vue'
import { api } from './api'
import type { AdminUser, AnalysisResult, ChatMessage, ConfigStatus, DashboardData, Dataset, KnowledgeItem, SessionSummary, ViewName } from './types'

const activeView = ref<ViewName>('overview')
const dashboard = ref<DashboardData | null>(null)
const datasets = ref<Dataset[]>([])
const config = ref<ConfigStatus | null>(null)
const knowledge = ref<KnowledgeItem[]>([])
const sessions = ref<SessionSummary[]>([])
const chatMessages = ref<ChatMessage[]>([])
const selectedDatasetId = ref<number | undefined>()
const selectedDataset = ref<Dataset | null>(null)
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
const knowledgeForm = ref({ title: '', content: '', category: 'business_rule' })
const currentAdmin = ref<AdminUser | null>(null)
const admins = ref<AdminUser[]>([])
const authChecked = ref(false)
const loginForm = ref({ username: '', password: '' })
const loginLoading = ref(false)
const newAdminForm = ref({ username: '', password: '' })
const creatingAdmin = ref(false)

const navItems: Array<{ id: ViewName; label: string; icon: string }> = [
  { id: 'overview', label: '工作台', icon: 'home' },
  { id: 'analyst', label: '智能分析', icon: 'spark' },
  { id: 'datasets', label: '数据源', icon: 'database' },
  { id: 'knowledge', label: '业务知识库', icon: 'book' },
  { id: 'accounts', label: '账户管理', icon: 'settings' },
  { id: 'settings', label: '系统配置', icon: 'settings' },
]

const pageTitle = computed(() => navItems.find((item) => item.id === activeView.value)?.label || 'DataAgent')
const examples = ['统计各地区销售额', '按月份展示销售额趋势', '查询投诉率最高的区域', '分析华东地区转化率']

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

async function addKnowledge() {
  if (!knowledgeForm.value.title || !knowledgeForm.value.content) return
  await api.createKnowledge({ ...knowledgeForm.value, dataset_id: selectedDatasetId.value })
  knowledge.value = await api.knowledge()
  dashboard.value = await api.dashboard()
  config.value = await api.config()
  knowledgeForm.value = { title: '', content: '', category: 'business_rule' }
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
    newAdminForm.value = { username: '', password: '' }
    admins.value = await api.admins()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '新增管理员失败'
  } finally {
    creatingAdmin.value = false
  }
}

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
        <div class="page-intro"><div><span class="eyebrow"><AppIcon name="database" :size="16" /> DATA CATALOG</span><h2>数据源与元数据</h2><p>上传 CSV / Excel，系统会自动识别字段、样例和缺失情况。</p></div></div>
        <div class="dataset-layout">
          <article class="panel upload-panel"><h3><AppIcon name="upload" />导入数据文件</h3><label class="drop-zone"><input type="file" accept=".csv,.xlsx" @change="chooseFile"/><AppIcon name="upload" :size="32"/><strong>{{ uploadFile?.name || '选择 CSV / Excel 文件' }}</strong><small>单文件最大 20MB</small></label><input v-model="uploadName" placeholder="数据集名称（可选）"/><textarea v-model="uploadDescription" placeholder="数据集用途与说明" rows="3"/><button class="primary-btn" :disabled="!uploadFile || uploading" @click="upload">{{ uploading ? '正在导入...' : '开始导入' }}</button></article>
          <article class="panel"><div class="panel-title"><div><small>CONNECTED</small><h3>已接入数据集</h3></div></div><div class="dataset-cards"><button v-for="dataset in datasets" :key="dataset.id" :class="{ selected: selectedDatasetId === dataset.id }" @click="inspectDataset(dataset.id)"><span><AppIcon name="database" /></span><div><strong>{{ dataset.name }}</strong><small>{{ dataset.description || '暂无描述' }}</small><em>{{ dataset.row_count.toLocaleString() }} 行 · {{ dataset.column_count }} 字段</em></div><i>{{ dataset.source_type }}</i></button></div></article>
        </div>
        <article v-if="selectedDataset" class="panel metadata-panel"><div class="panel-title"><div><small>METADATA</small><h3>{{ selectedDataset.name }} · 字段说明</h3></div></div><div class="table-scroll"><table><thead><tr><th>字段</th><th>类型</th><th>业务说明</th><th>样例值</th><th>缺失率</th></tr></thead><tbody><tr v-for="column in selectedDataset.columns" :key="column.name"><td><code>{{ column.name }}</code></td><td>{{ column.data_type }}</td><td>{{ column.description }}</td><td>{{ column.sample_value }}</td><td>{{ (column.null_rate * 100).toFixed(1) }}%</td></tr></tbody></table></div></article>
      </section>

      <section v-else-if="activeView === 'knowledge'" class="page">
        <div class="page-intro"><div><span class="eyebrow"><AppIcon name="book" :size="16" /> BUSINESS KNOWLEDGE</span><h2>指标口径与业务知识</h2><p>用于 RAG 检索，让智能体理解企业专有字段、指标和规则。</p></div></div>
        <div class="knowledge-layout">
          <article class="panel knowledge-form"><h3>新增知识片段</h3><input v-model="knowledgeForm.title" placeholder="标题，如：销售额口径"/><select v-model="knowledgeForm.category"><option value="metric">指标口径</option><option value="business_rule">业务规则</option><option value="data_dictionary">数据字典</option><option value="example">历史问答</option></select><textarea v-model="knowledgeForm.content" rows="7" placeholder="输入详细定义、适用范围和计算规则"/><button class="primary-btn" @click="addKnowledge">保存并加入索引</button></article>
          <div class="knowledge-list"><article v-for="item in knowledge" :key="item.id" class="knowledge-card"><span><AppIcon name="book" /></span><div><div class="knowledge-card-head"><strong>{{ item.title }}</strong><div><em>{{ item.category }}</em><button type="button" @click="deleteKnowledgeItem(item)">删除</button></div></div><p>{{ item.content }}</p></div></article></div>
        </div>
      </section>

      <section v-else-if="activeView === 'accounts'" class="page">
        <div class="page-intro"><div><span class="eyebrow"><AppIcon name="settings" :size="16" /> ACCOUNT MANAGEMENT</span><h2>账户管理</h2><p>初始管理员可以新增其他普通管理员；普通管理员只能查看账户列表。</p></div></div>
        <div class="account-layout">
          <article class="panel account-form">
            <h3>加入新管理员</h3>
            <template v-if="currentAdmin?.is_initial_admin">
              <input v-model="newAdminForm.username" placeholder="新管理员账号"/>
              <input v-model="newAdminForm.password" type="password" placeholder="新管理员密码，至少 6 位"/>
              <button class="primary-btn" :disabled="creatingAdmin" @click="addAdmin">{{ creatingAdmin ? '正在创建...' : '新增管理员' }}</button>
            </template>
            <div v-else class="permission-note"><AppIcon name="check" :size="16"/>当前账号是普通管理员，无权限新增其他管理员。</div>
          </article>
          <article class="panel">
            <div class="panel-title"><div><small>ADMINS</small><h3>管理员列表</h3></div></div>
            <div class="table-scroll"><table><thead><tr><th>ID</th><th>账号</th><th>角色</th><th>创建时间</th></tr></thead><tbody><tr v-for="admin in admins" :key="admin.id"><td>{{ admin.id }}</td><td>{{ admin.username }}</td><td>{{ admin.is_initial_admin ? '初始管理员' : '普通管理员' }}</td><td>{{ admin.created_at }}</td></tr></tbody></table></div>
          </article>
        </div>
      </section>

      <section v-else class="page">
        <div class="page-intro"><div><span class="eyebrow"><AppIcon name="settings" :size="16" /> SYSTEM SETTINGS</span><h2>模型与基础设施</h2><p>密钥仅从后端环境变量读取，不会返回给浏览器。</p></div></div>
        <div class="settings-grid">
          <article class="panel setting-card"><div class="setting-head"><span class="metric-icon blue"><AppIcon name="spark" /></span><div><h3>大语言模型</h3><p>OpenAI 兼容接口</p></div><em :class="{ ready: config?.llm_configured }">{{ config?.llm_configured ? '已配置' : '待配置' }}</em></div><dl><div><dt>模型</dt><dd>{{ config?.llm_model || '未设置' }}</dd></div><div><dt>API Key</dt><dd>仅后端可见</dd></div></dl></article>
          <article class="panel setting-card"><div class="setting-head"><span class="metric-icon cyan"><AppIcon name="book" /></span><div><h3>Embedding / RAG</h3><p>语义向量检索</p></div><em :class="{ ready: config?.embedding_configured }">{{ config?.embedding_configured ? '已启用' : '关键词降级' }}</em></div><dl><div><dt>Embedding 模型</dt><dd>{{ config?.embedding_model || '未配置' }}</dd></div><div><dt>向量存储</dt><dd>{{ config?.vector_store }}</dd></div><div><dt>已索引知识</dt><dd>{{ config?.vector_indexed_count ?? 0 }} 条</dd></div></dl></article>
          <article class="panel setup-card"><h3>API Key 配置位置</h3><p>复制 <code>backend/.env.example</code> 为 <code>backend/.env</code>，然后填写：</p><pre>LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=你要使用的模型</pre><p class="security-note">不要把 <code>.env</code> 提交到 Git；项目已在 <code>.gitignore</code> 中排除该文件。</p></article>
        </div>
      </section>
    </main>
  </div>
</template>
