<script setup lang="ts">
import * as echarts from 'echarts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AnalysisResult } from '../types'

const props = defineProps<{ result: AnalysisResult }>()
const target = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
const palette = ['#1677ff', '#13b8c8', '#7c4dff', '#f59e0b', '#10b981', '#ef5da8']

const option = computed<echarts.EChartsOption>(() => {
  const spec = props.result.chart
  const x = spec.x_field || props.result.columns[0]
  const y = spec.y_field || props.result.columns[props.result.columns.length - 1]
  const labels = [...new Set(props.result.rows.map((row) => String(row[x] ?? '')))]
  const seriesFields = spec.series_fields?.length
    ? spec.series_fields
    : (spec.series_field ? [spec.series_field] : [])
  const seriesLabel = (row: Record<string, unknown>) =>
    seriesFields.map((field) => String(row[field] ?? '未分类')).join(' / ')

  if (spec.type === 'pie') {
    const pieData = props.result.rows.map((row) => ({
      name: seriesFields.length ? `${String(row[x] ?? '')} / ${seriesLabel(row)}` : String(row[x] ?? ''),
      value: Number(row[y] ?? 0),
    }))
    return {
      tooltip: { trigger: 'item' },
      legend: { type: 'scroll', bottom: 0 },
      series: [{ type: 'pie', radius: ['42%', '70%'], data: pieData, itemStyle: { borderRadius: 7, borderWidth: 3, borderColor: '#fff' } }],
      color: palette,
    }
  }

  const seriesNames = seriesFields.length
    ? [...new Set(props.result.rows.map((row) => seriesLabel(row)))]
    : [spec.series_name || y]
  const series: echarts.SeriesOption[] = seriesNames.map((name, seriesIndex) => {
    const data = labels.map((label) => {
      const row = props.result.rows.find((item) =>
        String(item[x] ?? '') === label && (!seriesFields.length || seriesLabel(item) === name),
      )
      return row ? Number(row[y] ?? 0) : null
    })
    const color = palette[seriesIndex % palette.length]
    if (spec.type === 'line') {
      return {
        name, type: 'line', smooth: true, connectNulls: false, data, symbolSize: 6,
        lineStyle: { width: 2.5, color }, itemStyle: { color },
      }
    }
    return {
      name, type: 'bar', data,
      itemStyle: { color, borderRadius: [5, 5, 0, 0] },
    }
  })

  return {
    color: palette,
    dataZoom: labels.length > 16 ? [{ type: 'slider', height: 18, bottom: 16 }, { type: 'inside' }] : undefined,
    grid: {
      left: 62,
      right: 28,
      top: seriesFields.length ? 72 : 28,
      bottom: labels.length > 16 ? 78 : (labels.length > 20 ? 62 : 46),
    },
    tooltip: { trigger: 'axis' },
    legend: seriesFields.length ? { type: 'scroll', top: 2, left: 8, right: 8, textStyle: { color: '#5d7386', fontSize: 11 } } : undefined,
    xAxis: {
      type: 'category', data: labels,
      axisLine: { lineStyle: { color: '#d7e2ed' } },
      axisLabel: { color: '#718096', rotate: labels.length > 20 ? 35 : 0 },
    },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eef3f7' } }, axisLabel: { color: '#718096' } },
    series,
  }
})

function render() {
  if (!target.value) return
  chart ||= echarts.init(target.value)
  chart.setOption(option.value, true)
  chart.resize()
}

function resize() { chart?.resize() }
onMounted(() => { render(); window.addEventListener('resize', resize) })
onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart?.dispose() })
watch(option, () => nextTick(render), { deep: true })
</script>

<template><div ref="target" class="result-chart" role="img" :aria-label="result.chart.title" /></template>
