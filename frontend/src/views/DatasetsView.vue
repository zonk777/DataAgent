<script setup lang="ts">
import { ref } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import type { Dataset } from '../types'

defineProps<{ datasets: Dataset[]; selected: Dataset | null; selectedId: number | undefined }>()
const emit = defineEmits<{
  upload: [file: File, name: string, desc: string]
  inspect: [id: number]
}>()

const file = ref<File | null>(null)
const name = ref('')
const desc = ref('')
const uploading = ref(false)
const progress = ref(0)
const status = ref('')

function choose(e: Event) {
  file.value = (e.target as HTMLInputElement).files?.[0] || null
  if (file.value && !name.value) name.value = file.value.name.replace(/\.[^.]+$/, '')
  progress.value = 0; status.value = ''
}
async function doUpload() { if (!file.value) return; uploading.value = true; progress.value = 0; status.value = '准备上传'; await emit('upload', file.value, name.value, desc.value); uploading.value = false; status.value = '导入完成' }
</script>

<template>
  <section class="page">
    <div class="page-intro"><div><span class="eyebrow"><AppIcon name="database" :size="16" /> DATA CATALOG</span><h2>数据源与元数据</h2><p>上传 CSV / Excel / MySQL 导入，系统会自动识别字段、样例和缺失情况。</p></div></div>
    <div class="dataset-layout">
      <article class="panel upload-panel"><h3><AppIcon name="upload" />导入数据文件</h3>
        <label class="drop-zone"><input type="file" accept=".csv,.xls,.xlsx" @change="choose"/><AppIcon name="upload" :size="32"/><strong>{{ file?.name || '选择 CSV / Excel 文件' }}</strong><small>单文件最大 100MB</small></label>
        <input v-model="name" placeholder="数据集名称（可选）"/><textarea v-model="desc" placeholder="数据集用途与说明" rows="3"/>
        <div v-if="uploading || progress > 0" class="upload-progress"><div><span>{{ status || '等待上传' }}</span><b>{{ progress }}%</b></div><i><span :style="{ width: `${progress}%` }"/></i></div>
        <button class="primary-btn" :disabled="!file || uploading" @click="doUpload">{{ uploading ? '正在导入...' : '开始导入' }}</button>
      </article>
      <article class="panel"><div class="panel-title"><div><small>CONNECTED</small><h3>已接入数据集</h3></div></div>
        <div class="dataset-cards"><button v-for="ds in datasets" :key="ds.id" :class="{ selected: selectedId === ds.id }" @click="emit('inspect', ds.id)"><span><AppIcon name="database" /></span><div><strong>{{ ds.name }}</strong><small>{{ ds.description || '暂无描述' }}</small><em>{{ ds.row_count.toLocaleString() }} 行 · {{ ds.column_count }} 字段</em></div><i>{{ ds.source_type }}</i></button></div>
      </article>
    </div>
    <article v-if="selected" class="panel metadata-panel"><div class="panel-title"><div><small>METADATA</small><h3>{{ selected.name }} · 字段说明</h3></div></div>
      <div class="table-scroll"><table><thead><tr><th>字段</th><th>类型</th><th>业务说明</th><th>样例值</th><th>缺失率</th></tr></thead><tbody><tr v-for="col in selected.columns" :key="col.name"><td><code>{{ col.name }}</code></td><td>{{ col.data_type }}</td><td>{{ col.description }}</td><td>{{ col.sample_value }}</td><td>{{ (col.null_rate * 100).toFixed(1) }}%</td></tr></tbody></table></div>
    </article>
  </section>
</template>
