<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'

const logs = ref<any[]>([])
const filters = ref({ username: '', action: '', date_from: '', date_to: '' })
const loading = ref(false)
const error = ref('')

async function fetch() {
  loading.value = true; error.value = ''
  try {
    const params = new URLSearchParams()
    if (filters.value.username) params.set('username', filters.value.username)
    if (filters.value.action) params.set('action', filters.value.action)
    if (filters.value.date_from) params.set('date_from', filters.value.date_from)
    if (filters.value.date_to) params.set('date_to', filters.value.date_to)
    const resp = await fetch(`/api/v1/audit/logs?${params.toString()}`, { credentials: 'include' })
    if (!resp.ok) throw new Error((await resp.json()).detail || '查询失败')
    logs.value = await resp.json()
  } catch (err: any) { error.value = err.message || '查询审计日志失败' }
  finally { loading.value = false }
}

function exportExcel() {
  const params = new URLSearchParams()
  if (filters.value.username) params.set('username', filters.value.username)
  if (filters.value.action) params.set('action', filters.value.action)
  if (filters.value.date_from) params.set('date_from', filters.value.date_from)
  if (filters.value.date_to) params.set('date_to', filters.value.date_to)
  window.open(`/api/v1/audit/logs/export.xlsx?${params.toString()}`, '_blank')
}
</script>

<template>
  <section class="page">
    <div class="page-intro"><div><span class="eyebrow"><AppIcon name="settings" :size="16" /> AUDIT LOGS</span><h2>审计日志</h2><p>记录所有用户操作，支持按用户、操作类型、时间范围筛选，可导出 Excel。</p></div><button class="primary-btn" @click="fetch">查询</button></div>
    <div class="audit-filters" style="display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap">
      <input v-model="filters.username" placeholder="用户" style="width:120px"/>
      <select v-model="filters.action" style="width:140px"><option value="">全部操作</option><option value="login">登录</option><option value="analysis_request">分析请求</option><option value="export_report">导出报告</option><option value="create_knowledge">新增知识</option><option value="upload_dataset">上传数据</option><option value="delete_session">删除会话</option></select>
      <input v-model="filters.date_from" type="date" title="开始日期"/>
      <input v-model="filters.date_to" type="date" title="结束日期"/>
      <button @click="exportExcel" style="margin-left:auto">导出 Excel</button>
    </div>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <div v-if="loading" class="thinking"><i/><i/><i/><span>查询中...</span></div>
    <div v-else-if="logs.length" class="table-scroll"><table><thead><tr><th>ID</th><th>用户</th><th>操作</th><th>资源</th><th>详情</th><th>状态</th><th>时间</th></tr></thead><tbody><tr v-for="l in logs" :key="l.id"><td>{{ l.id }}</td><td>{{ l.username || '—' }}</td><td>{{ l.action }}</td><td>{{ l.resource_type }} {{ l.resource_id || '' }}</td><td>{{ l.detail }}</td><td>{{ l.status }}</td><td>{{ l.created_at }}</td></tr></tbody></table></div>
    <div v-else class="empty-chat"><AppIcon name="spark" :size="24"/><p>点击"查询"加载审计日志。</p></div>
  </section>
</template>
