<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppIcon from './components/AppIcon.vue'
import { api } from './api'
import type { AdminUser, AnalysisResult, ChatMessage, ConfigStatus, DashboardData, Dataset, KnowledgeItem, SessionSummary, ThinkingStep, ViewName } from './types'
import OverviewView from './views/OverviewView.vue'
import AnalystView from './views/AnalystView.vue'
import DatasetsView from './views/DatasetsView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import AccountsView from './views/AccountsView.vue'
import SettingsView from './views/SettingsView.vue'
import AuditView from './views/AuditView.vue'

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
const error = ref('')
const loading = ref(false)
const sessionId = ref<string>()
const thinkingSteps = ref<ThinkingStep[]>([])
const thinkingText = ref('')
const thinkingCollapsed = ref(false)
const streamCancel = ref<(() => void) | null>(null)
const currentAdmin = ref<AdminUser | null>(null)
const admins = ref<AdminUser[]>([])
const authChecked = ref(false)
const loginForm = ref({ username: '', password: '' })
const loginLoading = ref(false)

const navItems: Array<{ id: ViewName; label: string; icon: string }> = [
  { id: 'overview', label: '工作台', icon: 'home' },
  { id: 'analyst', label: '智能分析', icon: 'spark' },
  { id: 'datasets', label: '数据源', icon: 'database' },
  { id: 'knowledge', label: '业务知识库', icon: 'book' },
  { id: 'audit', label: '审计日志', icon: 'chart' },
  { id: 'accounts', label: '账户管理', icon: 'settings' },
  { id: 'settings', label: '系统配置', icon: 'settings' },
]
const pageTitle = computed(() => navItems.find(i => i.id === activeView)?.label || 'DataAgent')
const examples = ['统计各地区销售额', '按月份展示销售额趋势', '查询投诉率最高的区域', '分析华东地区转化率']

async function loadBase() {
  try {
    const [d, ds, c, k, s] = await Promise.all([api.dashboard(), api.datasets(), api.config(), api.knowledge(), api.sessions()])
    dashboard.value = d; datasets.value = ds; config.value = c; knowledge.value = k; sessions.value = s
    selectedDatasetId.value ||= ds[0]?.id
  } catch (err: any) { error.value = err.message || '后端服务未连接' }
}

async function bootstrap() {
  try { const me = await api.me(); currentAdmin.value = me.admin; await loadBase(); admins.value = await api.admins() }
  catch { currentAdmin.value = null }
  finally { authChecked.value = true }
}

async function login() {
  if (!loginForm.value.username || !loginForm.value.password) return
  loginLoading.value = true; error.value = ''
  try { const d = await api.login(loginForm.value.username, loginForm.value.password); currentAdmin.value = d.admin; loginForm.value.password = ''; await loadBase(); admins.value = await api.admins() }
  catch (err: any) { error.value = err.message || '登录失败' }
  finally { loginLoading.value = false }
}

async function logout() {
  await api.logout().catch(() => {})
  currentAdmin.value = null; dashboard.value = null; datasets.value = []; config.value = null; knowledge.value = []; sessions.value = []; chatMessages.value = []; result.value = null; sessionId.value = undefined; activeView.value = 'overview'
}

function analyze(q: string) {
  const v = q.trim(); if (!v) return
  loading.value = true; error.value = ''; activeView.value = 'analyst'

  // Reset streaming state
  thinkingSteps.value = []
  thinkingText.value = ''
  thinkingCollapsed.value = false

  // Cancel any in-flight stream
  streamCancel.value?.()

  chatMessages.value.push({ role: 'user', content: v })

  // Add a placeholder assistant message that will be updated
  const assistantMsg: ChatMessage = { role: 'assistant', content: '', payload: null }
  chatMessages.value.push(assistantMsg)

  streamCancel.value = api.analyzeStream(v, selectedDatasetId.value, sessionId.value, {
    onPlan(steps, intent, answerType) {
      thinkingSteps.value = steps.map((title, i) => ({
        id: i + 1,
        title,
        status: 'pending' as const,
      }))
    },
    onStep(stepId, title, status, detail) {
      const existing = thinkingSteps.value.find(s => s.id === stepId)
      if (existing) {
        existing.status = status as ThinkingStep['status']
        if (detail) existing.detail = detail
      } else if (status === 'running') {
        thinkingSteps.value.push({ id: stepId, title, status: 'running', detail })
      }
    },
    onThinking(content) {
      if (thinkingText.value) {
        thinkingText.value += '\n' + content
      } else {
        thinkingText.value = content
      }
    },
    onResult(data) {
      result.value = data
      sessionId.value = data.session_id
      assistantMsg.content = data.insights.join('\n')
      assistantMsg.payload = data
      assistantMsg._streamed = true
    },
    async onDone() {
      loading.value = false
      // Auto-collapse thinking after a short delay
      setTimeout(() => { thinkingCollapsed.value = true }, 1500)
      // Refresh sessions and dashboard
      sessions.value = await api.sessions()
      dashboard.value = await api.dashboard()
    },
    onError(message) {
      // Remove the placeholder assistant message
      chatMessages.value.pop()
      error.value = message || '分析失败'
      loading.value = false
    },
  })
}

function newSession() {
  sessionId.value = undefined
  chatMessages.value = []
  result.value = null
  thinkingSteps.value = []
  thinkingText.value = ''
  thinkingCollapsed.value = false
  loading.value = false
  error.value = ''
}

function toggleThinking() {
  thinkingCollapsed.value = !thinkingCollapsed.value
}

async function openSession(id: string) {
  loading.value = true; error.value = ''
  try { const d = await api.session(id); sessionId.value = d.id; selectedDatasetId.value = d.dataset_id || selectedDatasetId.value; chatMessages.value = d.messages; result.value = [...d.messages].reverse().find(m => m.role === 'assistant' && m.payload)?.payload || null; activeView.value = 'analyst' }
  catch (err: any) { error.value = err.message || '读取历史会话失败' }
  finally { loading.value = false }
}

async function deleteSession(id: string) {
  const s = sessions.value.find(i => i.id === id)
  if (!window.confirm(`确定删除「${s?.title || '该历史对话'}」吗？`)) return
  try { await api.deleteSession(id); sessions.value = sessions.value.filter(i => i.id !== id); if (sessionId.value === id) { sessionId.value = undefined; chatMessages.value = []; result.value = null }; dashboard.value = await api.dashboard() }
  catch (err: any) { error.value = err.message || '删除失败' }
}

async function inspectDataset(id: number) { activeView.value = 'datasets'; selectedDatasetId.value = id; selectedDataset.value = await api.dataset(id) }

async function doUpload(file: File, name: string, desc: string) {
  try { const created = await api.upload(file, name, desc); datasets.value = await api.datasets(); selectedDatasetId.value = created.id; selectedDataset.value = created; dashboard.value = await api.dashboard() }
  catch (err: any) { error.value = err.message || '上传失败' }
}

async function addKnowledge(f: { title: string; content: string; category: string }) {
  await api.createKnowledge({ ...f, dataset_id: selectedDatasetId.value })
  knowledge.value = await api.knowledge(); dashboard.value = await api.dashboard(); config.value = await api.config()
}

async function deleteKnowledge(item: KnowledgeItem) {
  if (!window.confirm(`确定删除「${item.title}」吗？`)) return
  try { await api.deleteKnowledge(item.id); knowledge.value = knowledge.value.filter(e => e.id !== item.id); dashboard.value = await api.dashboard(); config.value = await api.config() }
  catch (err: any) { error.value = err.message || '删除知识片段失败' }
}

async function addAdmin(f: { username: string; password: string; role: string; dataset_ids: number[] }) {
  try { await api.createAdmin(f); admins.value = await api.admins() }
  catch (err: any) { error.value = err.message || '新增管理员失败' }
}

async function updateAdmin(id: number, f: { role: string; dataset_ids: number[] }) {
  try { await api.updateAdmin(id, f); admins.value = await api.admins() }
  catch (err: any) { error.value = err.message || '更新管理员失败' }
}

async function deleteAdmin(id: number) {
  try { await api.deleteAdmin(id); admins.value = admins.value.filter(a => a.id !== id) }
  catch (err: any) { error.value = err.message || '删除管理员失败' }
}

onMounted(bootstrap)
</script>

<template>
  <div v-if="!authChecked" class="auth-screen"><div class="auth-card"><div class="brand-mark"><AppIcon name="chart" :size="28" /></div><h1>DataAgent</h1><p>正在检查登录状态...</p></div></div>

  <div v-else-if="!currentAdmin" class="auth-screen">
    <form class="auth-card login-card" @submit.prevent="login">
      <div class="brand-mark"><AppIcon name="chart" :size="28" /></div><h1>数据智能体服务系统</h1>
      <p>请使用管理员账号登录后继续访问系统。</p>
      <label>账号<input v-model="loginForm.username" autocomplete="username" placeholder="请输入账号" /></label>
      <label>密码<input v-model="loginForm.password" autocomplete="current-password" placeholder="请输入密码" type="password" /></label>
      <button class="primary-btn" :disabled="loginLoading">{{ loginLoading ? '登录中...' : '登录' }}</button>
      <div v-if="error" class="auth-error">{{ error }}</div>
    </form>
  </div>

  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark"><AppIcon name="chart" :size="24" /></div><div><strong>DataAgent</strong><small>企业数据智能体</small></div></div>
      <nav><button v-for="item in navItems" :key="item.id" :class="['nav-item', { active: activeView === item.id }]" @click="activeView = item.id"><AppIcon :name="item.icon" /><span>{{ item.label }}</span></button></nav>
      <div class="sidebar-foot"><div class="status-dot" :class="{ online: !error }" /><div><strong>{{ error ? '服务待连接' : '服务运行正常' }}</strong><small>{{ config?.llm_configured ? config.llm_model : '本地演示模式' }}</small></div></div>
    </aside>

    <main class="main-area">
      <header class="topbar">
        <div><p>DATA INTELLIGENCE</p><h1>{{ pageTitle }}</h1></div>
        <div class="top-actions">
          <select v-model="selectedDatasetId" aria-label="选择数据集"><option v-for="d in datasets" :key="d.id" :value="d.id">{{ d.name }}</option></select>
          <button class="account-chip" @click="activeView = 'accounts'">{{ currentAdmin?.username }}<span>{{ currentAdmin?.is_initial_admin ? '初始管理员' : '普通管理员' }}</span></button>
          <button class="logout-btn" @click="logout">退出</button>
        </div>
      </header>

      <div v-if="error" class="error-banner">{{ error }} <button @click="loadBase">重新连接</button></div>

      <OverviewView v-if="activeView === 'overview'" :dashboard="dashboard" :datasets="datasets" @analyze="analyze" @inspect="inspectDataset" @nav="(v: string) => activeView = v as ViewName" />
      <AnalystView v-else-if="activeView === 'analyst'" :sessions="sessions" :chat-messages="chatMessages" :result="result" :loading="loading" :session-id="sessionId" :examples="examples" :thinking-steps="thinkingSteps" :thinking-text="thinkingText" :thinking-collapsed="thinkingCollapsed" @analyze="analyze" @open-session="openSession" @delete-session="deleteSession" @new-session="newSession" @show-result="(m: ChatMessage) => { if (m.payload) result = m.payload }" @toggle-thinking="toggleThinking" />
      <DatasetsView v-else-if="activeView === 'datasets'" :datasets="datasets" :selected="selectedDataset" :selected-id="selectedDatasetId" @upload="doUpload" @inspect="inspectDataset" />
      <KnowledgeView v-else-if="activeView === 'knowledge'" :items="knowledge" @add="addKnowledge" @del="deleteKnowledge" />
      <AuditView v-else-if="activeView === 'audit'" />
      <AccountsView v-else-if="activeView === 'accounts'" :current="currentAdmin" :admins="admins" :datasets="datasets" @create="addAdmin" @update="updateAdmin" @delete="deleteAdmin" />
      <SettingsView v-else :config="config" />
    </main>
  </div>
</template>
