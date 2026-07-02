<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'
import type { AuditLog } from '../types'

const username = ref('')
const action = ref('')
const dateFrom = ref('')
const dateTo = ref('')

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

onMounted(() => {
  handleSearch()
})
</script>

<template>
  <section class="page audit-page">
    <div class="page-intro audit-intro">
      <div>
        <span class="eyebrow"><AppIcon name="chart" :size="16" /> AUDIT LOGS</span>
        <p>记录所有用户操作，支持按用户、操作类型、时间范围筛选，可导出 Excel。</p>
      </div>
    </div>

    <article class="panel audit-filter-panel">
      <div class="audit-toolbar">
        <label class="filter-item filter-user">
          <span class="filter-label">用户</span>
          <span class="control-wrap">
            <AppIcon name="search" :size="15" />
            <input v-model.trim="username" type="text" placeholder="输入用户名" />
          </span>
        </label>

        <label class="filter-item">
          <span class="filter-label">操作类型</span>
          <span class="control-wrap select-wrap">
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
          </span>
        </label>

        <label class="filter-item">
          <span class="filter-label">开始日期</span>
          <span class="control-wrap date-input-wrap">
            <input v-model="dateFrom" type="date" />
          </span>
        </label>

        <label class="filter-item">
          <span class="filter-label">结束日期</span>
          <span class="control-wrap date-input-wrap">
            <input v-model="dateTo" type="date" />
          </span>
        </label>

        <div class="filter-actions">
          <button class="audit-search-btn" :disabled="loading" @click="handleSearch">
            <AppIcon name="search" :size="16" />
            <span>{{ loading ? '查询中' : '查询' }}</span>
          </button>
          <button class="audit-export-btn" @click="handleExport">
            <AppIcon name="download" :size="16" />
            <span>导出</span>
          </button>
        </div>
      </div>
    </article>

    <div v-if="error" class="error-banner">{{ error }}</div>

    <div v-if="loading" class="thinking audit-loading">
      <i /><i /><i /><span>正在查询审计日志...</span>
    </div>

    <article v-else class="panel audit-data-panel">
      <div class="audit-data-head">
        <div>
          <small>QUERY RESULT</small>
          <strong>{{ logs.length ? `${logs.length} 条审计记录` : '审计记录' }}</strong>
        </div>
        <span v-if="logs.length">当前筛选条件下的操作流水</span>
      </div>

      <template v-if="logs.length">
        <div class="table-scroll audit-table-scroll">
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
                <td>
                  <span class="user-pill">{{ log.username || '—' }}</span>
                </td>
                <td><code>{{ log.action }}</code></td>
                <td>{{ log.resource_type }}</td>
                <td>{{ log.resource_id || '—' }}</td>
                <td class="detail-cell" :title="log.detail || ''">{{ log.detail || '—' }}</td>
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

      <div v-else class="empty-state audit-empty">
        <div class="empty-illustration"><AppIcon name="search" :size="42" /></div>
        <h3>暂无审计日志数据</h3>
        <p>请调整筛选条件后重试，或点击“查询”加载记录。</p>
      </div>
    </article>
  </section>
</template>

<style scoped>
.audit-page {
  padding-top: 30px;
}

.audit-intro {
  margin: 0 0 22px;
}

.audit-intro p {
  margin-top: 10px;
  font-size: 13px;
}

.audit-filter-panel {
  padding: 20px 22px;
  margin-bottom: 16px;
  border-radius: 18px;
}

.audit-toolbar {
  display: grid;
  grid-template-columns: minmax(170px, 1fr) minmax(190px, 1fr) minmax(170px, 1fr) minmax(170px, 1fr) auto;
  gap: 16px;
  align-items: end;
}

.filter-item {
  min-width: 0;
  display: grid;
  gap: 8px;
}

.filter-label {
  color: #52697f;
  font-size: 11px;
  font-weight: 800;
}

.control-wrap {
  height: 42px;
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #dce8f0;
  border-radius: 12px;
  padding: 0 12px;
  color: #8aa0b2;
  background: #fff;
  transition: border-color .15s ease, box-shadow .15s ease, background .15s ease;
}

.control-wrap:focus-within {
  border-color: #68afe8;
  box-shadow: 0 0 0 4px rgba(22, 119, 255, .08);
  background: #fbfdff;
}

.control-wrap input,
.control-wrap select {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  color: #304a60;
  font-size: 12px;
  background: transparent;
}

.control-wrap input::placeholder {
  color: #99aabb;
}

.select-wrap select {
  appearance: none;
  cursor: pointer;
}

.select-wrap {
  position: relative;
}

.select-wrap::after {
  content: '';
  width: 7px;
  height: 7px;
  border-right: 1.8px solid #8195a8;
  border-bottom: 1.8px solid #8195a8;
  transform: rotate(45deg);
  margin-left: 4px;
  pointer-events: none;
}

.date-input-wrap {
  padding-right: 8px;
}

.date-input-wrap input[type='date'] {
  color-scheme: light;
}

.filter-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 0;
}

.audit-search-btn,
.audit-export-btn {
  height: 42px;
  width: auto;
  min-width: 96px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: 12px;
  padding: 0 18px;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease, background .15s ease;
}

.audit-search-btn {
  border: 0;
  color: #fff;
  background: linear-gradient(110deg, #1677ff, #0eafd0);
  box-shadow: 0 9px 18px rgba(22, 119, 255, .2);
}

.audit-search-btn:hover:not(:disabled),
.audit-export-btn:hover {
  transform: translateY(-1px);
}

.audit-search-btn:disabled {
  opacity: .6;
  cursor: not-allowed;
}

.audit-export-btn {
  border: 1px solid #d6e5ef;
  color: #31566f;
  background: linear-gradient(180deg, #fff, #f6fbff);
  box-shadow: 0 8px 16px rgba(38, 77, 108, .06);
}

.audit-export-btn:hover {
  border-color: #9dc9eb;
  color: #1677ff;
  background: #f2f8ff;
}

.audit-data-panel {
  min-height: 360px;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
  border-radius: 18px;
}

.audit-data-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 18px 21px;
  border-bottom: 1px solid #edf2f6;
  background: linear-gradient(180deg, #fff, #fbfdff);
}

.audit-data-head small,
.audit-data-head strong {
  display: block;
}

.audit-data-head small {
  color: #31a5ba;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 1.5px;
}

.audit-data-head strong {
  margin-top: 5px;
  color: #183851;
  font-size: 15px;
}

.audit-data-head span {
  color: #8a9ba8;
  font-size: 11px;
}

.audit-table-scroll {
  padding: 0;
}

.audit-table-scroll table {
  font-size: 11px;
}

.audit-table-scroll th {
  padding: 12px 14px;
  color: #5f7488;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .5px;
  background: #f2f7fb;
}

.audit-table-scroll td {
  padding: 12px 14px;
  color: #425b70;
  font-size: 11px;
}

.user-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 4px 9px;
  border-radius: 999px;
  color: #176f95;
  background: #e9f8fb;
  font-weight: 800;
}

.detail-cell {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #5b7286;
}

.time-cell {
  white-space: nowrap;
  color: #6f8294;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  min-height: 23px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 800;
}

.status-badge.success {
  color: #078b65;
  background: #e6f8ef;
}

.status-badge.failed {
  color: #c24154;
  background: #fff1f3;
}

.audit-table-scroll code {
  border-radius: 8px;
  padding: 4px 7px;
  color: #1d6d9a;
  background: #eef7ff;
  font-size: 10px;
}

.audit-empty {
  flex: 1;
  min-height: 300px;
  padding: 62px 24px;
}

.empty-illustration {
  width: 76px;
  height: 76px;
  display: grid;
  place-items: center;
  margin-bottom: 14px;
  border-radius: 22px;
  color: #52a9d6;
  background: linear-gradient(135deg, #eef7ff, #e8fbf7);
}

.audit-empty h3 {
  color: #2f4960;
}

.audit-empty p {
  color: #91a2b1;
}

.audit-loading {
  justify-content: center;
  margin: 18px 0;
}

@media (max-width: 1280px) {
  .audit-toolbar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .filter-actions {
    justify-content: flex-end;
  }
}

@media (max-width: 720px) {
  .audit-toolbar {
    grid-template-columns: 1fr;
  }

  .filter-actions {
    justify-content: stretch;
  }

  .audit-search-btn,
  .audit-export-btn {
    flex: 1;
  }
}
</style>
