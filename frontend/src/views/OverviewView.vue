<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import type { DashboardData, Dataset } from '../types'

defineProps<{ dashboard: DashboardData | null; datasets: Dataset[] }>()
const emit = defineEmits<{ analyze: [q: string]; inspect: [id: number]; nav: [view: string] }>()

const question = ref('分析近30天各地区销售额趋势')
const examples = ['统计各地区销售额', '按月份展示销售额趋势', '查询投诉率最高的区域', '分析华东地区转化率']
</script>

<template>
  <section class="page overview-page">
    <div class="hero-card">
      <div class="hero-copy">
        <span class="eyebrow"><AppIcon name="spark" :size="16" /> AI 数据分析助手</span>
        <h2>把业务问题，直接变成<br><em>可信的数据结论</em></h2>
        <p>自然语言提问，自动完成数据理解、SQL 生成、安全执行、图表展示和分析报告。</p>
        <div class="hero-input">
          <input v-model="question" @keyup.enter="emit('analyze', question)" placeholder="例如：分析本季度各区域销售额变化原因" />
          <button @click="emit('analyze', question)"><AppIcon name="send" :size="18" />开始分析</button>
        </div>
        <div class="example-row"><span>试试：</span><button v-for="item in examples.slice(0, 3)" :key="item" @click="emit('analyze', item)">{{ item }}</button></div>
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
        <button v-for="(item, index) in examples" :key="item" @click="emit('analyze', item)"><span>{{ index + 1 }}</span><div><strong>{{ item }}</strong><small>{{ index % 2 ? '趋势对比与可视化' : '指标查询与维度拆解' }}</small></div><b>→</b></button>
      </article>
      <article class="panel data-panel"><div class="panel-title"><div><small>DATA ASSETS</small><h3>数据资产</h3></div><button @click="emit('nav', 'datasets')">管理数据源</button></div>
        <div v-for="dataset in datasets.slice(0, 4)" :key="dataset.id" class="dataset-line" @click="emit('inspect', dataset.id)">
          <span><AppIcon name="database" /></span><div><strong>{{ dataset.name }}</strong><small>{{ dataset.row_count.toLocaleString() }} 行 · {{ dataset.column_count }} 个字段</small></div><i>{{ dataset.source_type.toUpperCase() }}</i>
        </div>
      </article>
    </div>
  </section>
</template>
