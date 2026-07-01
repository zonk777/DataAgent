<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'
import type { AuditLog } from '../types'

// ---- 筛选状态 ----
const username = ref('')
const action = ref('')
const dateFrom = ref('')
const dateTo = ref('')

// ---- 数据与交互 ----
const logs = ref<AuditLog[]>([])
const loading = ref(false)
const error = ref('')

function buildQuery(): string {
  const params: string[] = []
  if (username.value) params.push(`username=${encodeURIComponent(username.value)}`)
  if (action.value) params.push(`action=${encodeURIComponent(action.value)}`)
  if (dateFrom.value) params.push(`date_from=${encodeURIComponent(dateFrom.value)}`)
  if (dateTo.value) params.push(`date_to=${encodeURIComponent(dateTo.value)}`)
  return params.length ? `?${params.join('&')}` : ''
}

async function handleSearch() {
  loading.value = true
  error.value = ''
  try {
    logs.value = await api.auditLogs(buildQuery())
  } catch (err: any) {
    error.value = err.message || '查询审计日志失败'
  } finally {
    loading.value = false
  }
}

function handleExport() {
  window.open(api.auditExportUrl(buildQuery()), '_blank')
}
</script>

<template>
  <section class="page">
    <!-- 头部 -->
    <div class="page-intro">
      <div>
        <span class="eyebrow"><AppIcon name="chart" :size="16" /> AUDIT LOGS</span>
        <h2>审计日志</h2>
        <p>记录所有用户操作，支持按用户、操作类型、时间范围筛选，可导出 Excel。</p>
      </div>
    </div>

    <!-- 筛选工具栏 -->
    <article class="panel audit-filter-panel">
      <div class="audit-toolbar">
        <label class="filter-item">
          <span class="filter-label">用户</span>
          <select v-model="username">
            <option value="">请选择用户</option>
          </select>
        </label>

        <label class="filter-item">
          <span class="filter-label">操作类型</span>
          <select v-model="action">
            <option value="">全部操作</option>
            <option value="login">登录</option>
            <option value="analysis_request">分析请求</option>
            <option value="export_report">导出报告</option>
            <option value="create_knowledge">新增知识</option>
            <option value="upload_dataset">上传数据</option>
            <option value="delete_session">删除会话</option>
            <option value="update_knowledge">编辑知识</option>
            <option value="delete_knowledge">删除知识</option>
            <option value="export_audit">导出审计</option>
            <option value="reindex_knowledge">重建索引</option>
          </select>
        </label>

        <label class="filter-item">
          <span class="filter-label">开始日期</span>
          <span class="date-input-wrap">
            <input v-model="dateFrom" type="date" placeholder="yyyy/mm/dd" />
            <AppIcon name="chart" :size="14" />
          </span>
        </label>

        <label class="filter-item">
          <span class="filter-label">结束日期</span>
          <span class="date-input-wrap">
            <input v-model="dateTo" type="date" placeholder="yyyy/mm/dd" />
            <AppIcon name="chart" :size="14" />
          </span>
        </label>

        <div class="filter-actions">
          <button class="primary-btn" :disabled="loading" @click="handleSearch">
            <AppIcon name="spark" :size="15" /> 查询
          </button>
          <button class="secondary-btn" @click="handleExport">
            <AppIcon name="file" :size="15" /> 导出
          </button>
        </div>
      </div>
    </article>

    <!-- 错误提示 -->
    <div v-if="error" class="error-banner">{{ error }}</div>

    <!-- 加载中 -->
    <div v-if="loading" class="thinking"><i /><i /><i /><span>正在查询审计日志...</span></div>

    <!-- 数据表格 / 空状态 -->
    <article v-else class="panel audit-data-panel">
      <template v-if="logs.length">
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>用户</th>
                <th>操作类型</th>
                <th>资源类型</th>
                <th>资源 ID</th>
                <th>详情</th>
                <th>状态</th>
                <th>操作时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="log in logs" :key="log.id">
                <td>{{ log.id }}</td>
                <td>{{ log.username || '—' }}</td>
                <td><code>{{ log.action }}</code></td>
                <td>{{ log.resource_type }}</td>
                <td>{{ log.resource_id || '—' }}</td>
                <td class="detail-cell">{{ log.detail || '—' }}</td>
                <td>
                  <span :class="['status-badge', log.status === 'success' ? 'success' : 'failed']">
                    {{ log.status === 'success' ? '成功' : '失败' }}
                  </span>
                </td>
                <td class="time-cell">{{ log.created_at }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <!-- 空状态 -->
      <div v-else class="empty-state">
        <AppIcon name="chart" :size="40" />
        <h3>暂无审计日志数据</h3>
        <p>请调整筛选条件后重试</p>
      </div>
    </article>
  </section>
</template>

<style scoped>
/* 筛选面板 */
.audit-filter-panel {
  padding: 20px 24px;
  margin-bottom: 16px;
}

.audit-toolbar {
  display: flex;
  align-items: flex-end;
  gap: 20px;
  flex-wrap: wrap;
}

.filter-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 130px;
}

.filter-label {
  font-size: 12px;
  font-weight: 600;
  color: #667085;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.filter-item select,
.filter-item input[type='date'] {
  height: 36px;
  padding: 0 10px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  font-size: 13px;
  color: #344054;
  background: #fff;
  outline: none;
  transition: border-color 0.15s;
}

.filter-item select:focus,
.filter-item input[type='date']:focus {
  border-color: #2e74b5;
  box-shadow: 0 0 0 2px rgba(46, 116, 181, 0.12);
}

.date-input-wrap {
  display: flex;
  align-items: center;
  position: relative;
}

.date-input-wrap input[type='date'] {
  width: 100%;
  padding-right: 30px;
}

.date-input-wrap :deep(svg) {
  position: absolute;
  right: 9px;
  pointer-events: none;
  color: #98a2b3;
}

.filter-actions {
  display: flex;
  gap: 10px;
  margin-left: auto;
  align-items: flex-end;
  padding-bottom: 1px;
}

.secondary-btn {
  height: 36px;
  padding: 0 18px;
  border: 1px solid #d0d5dd;
  border-radius: 6px;
  background: #fff;
  color: #344054;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: background 0.15s, border-color 0.15s;
}

.secondary-btn:hover {
  background: #f9fafb;
  border-color: #98a2b3;
}

.secondary-btn :deep(svg) {
  color: #667085;
}

/* 数据面板 */
.audit-data-panel {
  min-height: 320px;
  display: flex;
  flex-direction: column;
}

/* 空状态 */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 24px;
  color: #667085;
}

.empty-state :deep(svg) {
  color: #d0d5dd;
  margin-bottom: 16px;
}

.empty-state h3 {
  font-size: 16px;
  font-weight: 600;
  color: #344054;
  margin: 0 0 6px;
}

.empty-state p {
  font-size: 13px;
  color: #98a2b3;
  margin: 0;
}

/* 表格增强 */
.detail-cell {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #475467;
}

.time-cell {
  white-space: nowrap;
  font-size: 12px;
  color: #667085;
}

.status-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.status-badge.success {
  background: #ecfdf3;
  color: #027a48;
}

.status-badge.failed {
  background: #fef3f2;
  color: #b42318;
}

.table-scroll th {
  white-space: nowrap;
  font-size: 12px;
  font-weight: 600;
  color: #667085;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.table-scroll td {
  font-size: 13px;
}

.table-scroll code {
  background: #f2f4f7;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  color: #344054;
}
</style>
