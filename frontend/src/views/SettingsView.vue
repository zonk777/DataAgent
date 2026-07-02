<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import AppIcon from '../components/AppIcon.vue'
import { api } from '../api'
import type { ConfigStatus } from '../types'

const props = defineProps<{ config: ConfigStatus | null }>()
const emit = defineEmits<{ updated: [config: ConfigStatus] }>()

type ApiMode = 'system' | 'custom'

const apiMode = ref<ApiMode>('system')
const customProvider = ref('deepseek')
const llmApiKey = ref('')
const customBaseUrl = ref('https://api.deepseek.com')
const customModel = ref('deepseek-v4-flash')
const embeddingApiKey = ref('')
const customEmbeddingBaseUrl = ref('https://api.siliconflow.cn/v1/embeddings')
const customEmbeddingModel = ref('Qwen/Qwen3-VL-Embedding-8B')
const saving = ref(false)
const saveMessage = ref('')
const saveError = ref('')

const providerOptions = [
  {
    value: 'deepseek',
    label: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com',
    models: ['deepseek-v4-flash', 'deepseek-chat', 'deepseek-reasoner'],
  },
  {
    value: 'openai',
    label: 'OpenAI 兼容',
    baseUrl: 'https://api.openai.com/v1',
    models: ['gpt-4.1-mini', 'gpt-4.1', 'gpt-4o-mini'],
  },
  {
    value: 'siliconflow',
    label: 'SiliconFlow',
    baseUrl: 'https://api.siliconflow.cn/v1',
    models: ['deepseek-ai/DeepSeek-V3', 'Qwen/Qwen3-32B', 'THUDM/GLM-4-9B-0414'],
  },
  {
    value: 'custom',
    label: '自定义服务商',
    baseUrl: '',
    models: [''],
  },
]

const currentProvider = computed(() => providerOptions.find(item => item.value === customProvider.value) || providerOptions[0])

watch(() => props.config?.api_mode, (mode) => {
  if (mode === 'system' || mode === 'custom') apiMode.value = mode
}, { immediate: true })

watch(customProvider, () => {
  customBaseUrl.value = currentProvider.value.baseUrl
  customModel.value = currentProvider.value.models[0] || ''
})

async function saveApiSettings() {
  saving.value = true
  saveMessage.value = ''
  saveError.value = ''
  try {
    const updated = await api.saveApiSettings(
      apiMode.value === 'system'
        ? { mode: 'system' }
        : {
            mode: 'custom',
            llm_api_key: llmApiKey.value.trim() || undefined,
            llm_base_url: customBaseUrl.value.trim(),
            llm_model: customModel.value.trim(),
            embedding_api_key: embeddingApiKey.value.trim() || undefined,
            embedding_base_url: customEmbeddingBaseUrl.value.trim(),
            embedding_model: customEmbeddingModel.value.trim(),
          },
    )
    emit('updated', updated)
    llmApiKey.value = ''
    embeddingApiKey.value = ''
    saveMessage.value = apiMode.value === 'system' ? '已切换为系统 API' : '自定义 API 已保存并启用'
  } catch (err: any) {
    saveError.value = err.message || '保存 API 设置失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="page">
    <div class="page-intro">
      <div>
        <span class="eyebrow"><AppIcon name="settings" :size="16" /> SYSTEM SETTINGS</span>
        <h2>模型与 API 设置</h2>
        <p>用户可以选择使用系统默认 API，也可以在前端填写自己的 API Key，由后端保存并切换生效。</p>
      </div>
    </div>

    <div class="settings-grid">
      <article class="panel setting-card">
        <div class="setting-head">
          <span class="metric-icon blue"><AppIcon name="spark" /></span>
          <div>
            <h3>大语言模型</h3>
            <p>OpenAI 兼容接口</p>
          </div>
          <em :class="{ ready: config?.llm_configured }">
            {{ config?.llm_configured ? '已配置' : '待配置' }}
          </em>
        </div>
        <dl>
          <div>
            <dt>当前模型</dt>
            <dd>{{ config?.llm_model || '未设置' }}</dd>
          </div>
          <div>
            <dt>API Key</dt>
            <dd>不展示</dd>
          </div>
        </dl>
      </article>

      <article class="panel setting-card">
        <div class="setting-head">
          <span class="metric-icon cyan"><AppIcon name="book" /></span>
          <div>
            <h3>Embedding / RAG</h3>
            <p>语义向量检索</p>
          </div>
          <em :class="{ ready: config?.embedding_configured }">
            {{ config?.embedding_configured ? '已启用' : '关键词降级' }}
          </em>
        </div>
        <dl>
          <div>
            <dt>Embedding 模型</dt>
            <dd>{{ config?.embedding_model || '未配置' }}</dd>
          </div>
          <div>
            <dt>向量服务</dt>
            <dd>{{ config?.vector_store }}</dd>
          </div>
          <div>
            <dt>已索引知识</dt>
            <dd>{{ config?.vector_indexed_count ?? 0 }} 条</dd>
          </div>
        </dl>
      </article>

      <article class="panel setup-card api-setup-card">
        <div class="api-setup-head">
          <div>
            <h3>API 设置</h3>
            <p>选择系统 API 时无需填写任何内容；选择自定义 API 时，填写自己的 Key 和模型后保存，系统会在后端替换生效。</p>
          </div>
          <span class="api-secret-badge">密钥不回显</span>
        </div>

        <div class="api-choice-grid" role="radiogroup" aria-label="API 使用方式">
          <button
            type="button"
            :class="['api-choice-card', { active: apiMode === 'system' }]"
            role="radio"
            :aria-checked="apiMode === 'system'"
            @click="apiMode = 'system'"
          >
            <span><AppIcon name="check" :size="17" /></span>
            <div>
              <h4>使用系统 API</h4>
              <p>使用项目内置 API Key。用户不需要填写 Key、Base URL 或模型，适合演示和团队共享。</p>
            </div>
          </button>

          <button
            type="button"
            :class="['api-choice-card', { active: apiMode === 'custom' }]"
            role="radio"
            :aria-checked="apiMode === 'custom'"
            @click="apiMode = 'custom'"
          >
            <span><AppIcon name="settings" :size="17" /></span>
            <div>
              <h4>接入自己的 API</h4>
              <p>在前端填写自己的 API Key、接口地址和模型，提交后由后端保存并替换当前配置。</p>
            </div>
          </button>
        </div>

        <section v-if="apiMode === 'system'" class="system-api-panel">
          <div>
            <h4>当前选择：系统默认 API</h4>
            <p>系统 API 的密钥由后端托管，前端只展示当前状态和模型名称，不展示真实 Key。</p>
          </div>
          <dl>
            <div>
              <dt>大模型</dt>
              <dd>{{ config?.llm_model || '未设置' }}</dd>
            </div>
            <div>
              <dt>Embedding</dt>
              <dd>{{ config?.embedding_model || '未设置' }}</dd>
            </div>
            <div>
              <dt>向量服务</dt>
              <dd>{{ config?.vector_store || '未设置' }}</dd>
            </div>
          </dl>
        </section>

        <section v-else class="custom-api-panel">
          <div class="custom-form-card">
            <h4>自定义 API 参数</h4>
            <p class="custom-form-tip">
              Key 会发送到后端保存，保存成功后输入框会清空；再次进入页面不会回显真实 Key。
              如果之前已经保存过自定义 Key，留空则沿用已保存的 Key。
            </p>
            <div class="custom-form-grid">
              <label>
                <span>服务商</span>
                <select v-model="customProvider">
                  <option v-for="item in providerOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </option>
                </select>
              </label>

              <label>
                <span>大模型 API Key</span>
                <input v-model="llmApiKey" type="password" autocomplete="off" placeholder="请输入你的大模型 API Key" />
              </label>

              <label>
                <span>LLM Base URL</span>
                <input v-model="customBaseUrl" placeholder="例如 https://api.deepseek.com" />
              </label>

              <label>
                <span>LLM 模型</span>
                <select v-if="customProvider !== 'custom'" v-model="customModel">
                  <option v-for="model in currentProvider.models" :key="model" :value="model">
                    {{ model }}
                  </option>
                </select>
                <input v-else v-model="customModel" placeholder="请输入模型名称" />
              </label>

              <label>
                <span>Embedding API Key</span>
                <input v-model="embeddingApiKey" type="password" autocomplete="off" placeholder="请输入你的 Embedding API Key" />
              </label>

              <label>
                <span>Embedding Base URL</span>
                <input v-model="customEmbeddingBaseUrl" placeholder="嵌入模型接口地址" />
              </label>

              <label class="full-row">
                <span>Embedding 模型</span>
                <input v-model="customEmbeddingModel" placeholder="例如 Qwen/Qwen3-VL-Embedding-8B" />
              </label>
            </div>
          </div>
        </section>

        <div class="api-save-row">
          <button class="api-save-btn" :disabled="saving" @click="saveApiSettings">
            <AppIcon name="check" :size="17" />
            {{ saving ? '保存中...' : apiMode === 'system' ? '启用系统 API' : '保存并启用自定义 API' }}
          </button>
          <span v-if="saveMessage" class="api-save-message success">{{ saveMessage }}</span>
          <span v-if="saveError" class="api-save-message error">{{ saveError }}</span>
        </div>

        <p class="security-note">
          安全说明：真实 Key 只由后端保存，前端不会回显，也不会通过配置状态接口返回；演示环境可直接使用本功能，生产环境建议配合 HTTPS 与密钥管理服务。
        </p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.api-setup-card {
  display: grid;
  gap: 18px;
}

.api-setup-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.api-setup-head h3 {
  margin: 0 0 7px;
  font-size: 18px;
  color: #173751;
}

.api-setup-head p {
  margin: 0;
  color: #657b8d;
  font-size: 12px;
  line-height: 1.7;
}

.api-secret-badge {
  flex-shrink: 0;
  color: #087456;
  background: #e6faf1;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 10px;
  font-weight: 800;
}

.api-choice-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.api-choice-card {
  display: flex;
  gap: 13px;
  padding: 18px;
  min-height: 96px;
  border: 1px solid #e0e9ef;
  border-radius: 13px;
  background: #fbfdff;
  color: inherit;
  text-align: left;
  transition: border-color 0.18s, background 0.18s, box-shadow 0.18s;
}

.api-choice-card:hover {
  border-color: #b9ddff;
  box-shadow: 0 8px 18px rgba(32, 92, 140, 0.06);
}

.api-choice-card.active {
  border-color: #9bd0ff;
  background: linear-gradient(135deg, #edf7ff 0%, #f1fffd 100%);
  box-shadow: inset 0 0 0 1px rgba(22, 119, 255, 0.08);
}

.api-choice-card > span {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  border-radius: 12px;
  color: #1677ff;
  background: #e9f2ff;
}

.api-choice-card h4,
.system-api-panel h4,
.custom-form-card h4 {
  margin: 0 0 8px;
  color: #253f56;
  font-size: 14px;
}

.api-choice-card p,
.system-api-panel p,
.custom-form-tip {
  margin: 0;
  color: #6d8192;
  font-size: 11px;
  line-height: 1.7;
}

.system-api-panel {
  display: grid;
  grid-template-columns: minmax(260px, 0.75fr) 1.25fr;
  gap: 16px;
  align-items: start;
  padding: 18px;
  border: 1px solid #dfeaf3;
  border-radius: 13px;
  background: #f8fbfd;
}

.system-api-panel dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}

.system-api-panel dl > div {
  padding: 13px;
  border: 1px solid #e5edf3;
  border-radius: 11px;
  background: white;
}

.system-api-panel dt {
  color: #8798a7;
  font-size: 10px;
}

.system-api-panel dd {
  margin: 7px 0 0;
  color: #1f354b;
  font-size: 12px;
  font-weight: 800;
  word-break: break-all;
}

.custom-api-panel {
  display: block;
}

.custom-form-card {
  border: 1px solid #dfeaf3;
  border-radius: 13px;
  padding: 18px;
  background: #f8fbfd;
}

.custom-form-tip {
  margin-bottom: 14px;
}

.custom-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.custom-form-grid label {
  display: grid;
  gap: 7px;
  color: #61758a;
  font-size: 10px;
  font-weight: 800;
}

.custom-form-grid .full-row {
  grid-column: 1 / -1;
}

.custom-form-grid input,
.custom-form-grid select {
  width: 100%;
  border: 1px solid #d9e4ec;
  border-radius: 9px;
  padding: 10px 11px;
  outline: 0;
  color: #263f55;
  background: #fff;
  font-size: 11px;
}

.custom-form-grid input:focus,
.custom-form-grid select:focus {
  border-color: #1677ff;
  box-shadow: 0 0 0 3px rgba(22, 119, 255, 0.1);
}

.api-save-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.api-save-btn {
  border: 0;
  appearance: none;
  min-width: 168px;
  min-height: 52px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-radius: 14px;
  color: white;
  background: linear-gradient(110deg, #1677ff, #0eafd0);
  font-weight: 800;
  font-size: 18px;
  line-height: 1;
  padding: 0 24px;
  box-shadow: 0 12px 26px rgba(22, 119, 255, 0.24);
  transition: transform 0.18s ease, box-shadow 0.18s ease, filter 0.18s ease;
}

.api-save-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.03);
  box-shadow: 0 16px 30px rgba(22, 119, 255, 0.28);
}

.api-save-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.api-save-message {
  font-size: 11px;
  font-weight: 800;
}

.api-save-message.success {
  color: #0b8a63;
}

.api-save-message.error {
  color: #c53c55;
}

@media (max-width: 1100px) {
  .system-api-panel {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 820px) {
  .api-choice-grid,
  .system-api-panel dl,
  .custom-form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
