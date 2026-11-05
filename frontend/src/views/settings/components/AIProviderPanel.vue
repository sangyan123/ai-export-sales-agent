<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Connection } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchAIProvider, testAIProvider, updateAIProvider } from '@/api/tenants'
import { ApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import type { AIProviderConfig, AIProviderUpdatePayload } from '@/types/tenant'
import { formatDateTime } from '@/utils/format'

defineOptions({ name: 'AIProviderPanel' })

const auth = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const config = ref<AIProviderConfig | null>(null)

const canUpdate = auth.hasPermission('tenant:update')

const form = reactive({
  provider: 'openai',
  api_key: '',
  base_url: '',
  model_id: '',
  enabled: false,
})

const baseUrlPlaceholder = 'https:' + '//api.openai.com' + '/v1（兼容接口必填）'

const apiKeyPlaceholder = computed(() => {
  if (config.value?.api_key_set) {
    return '已设置（' + (config.value.api_key_hint ?? '') + '），留空保持不变'
  }
  return 'sk-...'
})

async function load() {
  loading.value = true
  try {
    config.value = await fetchAIProvider()
    form.provider = config.value.provider ?? 'openai'
    form.base_url = config.value.base_url ?? ''
    form.model_id = config.value.model_id ?? ''
    form.enabled = config.value.enabled
    form.api_key = ''
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载模型配置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const payload: AIProviderUpdatePayload = {
      provider: form.provider,
      base_url: form.base_url.trim() || null,
      model_id: form.model_id.trim() || null,
      enabled: form.enabled,
    }
    if (form.api_key.trim()) {
      payload.api_key = form.api_key.trim()
    }
    config.value = await updateAIProvider(payload)
    form.api_key = ''
    ElMessage.success('模型配置已保存')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '保存模型配置失败')
  } finally {
    saving.value = false
  }
}

async function runTest() {
  testing.value = true
  try {
    const result = await testAIProvider()
    if (result.status === 'SUCCESS') {
      ElMessage.success('连通性测试成功：' + result.message)
    } else {
      ElMessage.error('连通性测试失败：' + result.message)
    }
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '测试请求失败')
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<template>
  <el-card v-loading="loading" shadow="never" class="provider-card">
    <template #header>
      <div class="card-head">
        <span>模型配置（AI Provider）</span>
        <el-tag v-if="config?.enabled" type="success" size="small" effect="plain">
          已启用租户配置
        </el-tag>
        <el-tag v-else type="info" size="small" effect="plain">使用环境变量配置</el-tag>
      </div>
    </template>

    <el-alert v-if="!config?.api_key_set" type="info" :closable="false" show-icon class="provider-alert">
      当前未配置租户级模型。启用后，AI 解析和邮件生成将使用此处配置的模型；未启用时回退到系统环境变量（
      <code>{{ config?.env_fallback?.provider ?? '未配置' }}</code> /
      <code>{{ config?.env_fallback?.model_id ?? '—' }}</code>）。
    </el-alert>

    <el-form label-width="110px" class="provider-form" :disabled="!canUpdate">
      <el-form-item label="Provider">
        <el-select v-model="form.provider" style="width: 240px">
          <el-option label="OpenAI" value="openai" />
          <el-option label="OpenAI 兼容（DeepSeek 等）" value="openai-compatible" />
        </el-select>
      </el-form-item>
      <el-form-item label="API Key">
        <el-input
          v-model="form.api_key"
          type="password"
          show-password
          :placeholder="apiKeyPlaceholder"
          style="width: 420px"
        />
      </el-form-item>
      <el-form-item label="Base URL">
        <el-input
          v-model="form.base_url"
          :placeholder="baseUrlPlaceholder"
          style="width: 420px"
        />
      </el-form-item>
      <el-form-item label="模型名称">
        <el-input v-model="form.model_id" placeholder="gpt-4o-mini / deepseek-chat" style="width: 420px" />
      </el-form-item>
      <el-form-item label="启用">
        <el-switch v-model="form.enabled" />
        <span class="hint">启用后本企业的 AI 功能优先使用此配置</span>
      </el-form-item>

      <el-form-item v-if="config?.last_test_at" label="上次测试">
        <el-tag :type="config.last_test_status === 'SUCCESS' ? 'success' : 'danger'" size="small" effect="plain">
          {{ config.last_test_status === 'SUCCESS' ? '成功' : '失败' }}
        </el-tag>
        <span class="hint test-hint">
          {{ config.last_test_message }} · {{ formatDateTime(config.last_test_at) }}
        </span>
      </el-form-item>

      <el-form-item v-if="canUpdate">
        <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
        <el-button :icon="Connection" :loading="testing" @click="runTest">测试连通性</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<style scoped>
.provider-card {
  margin-top: 16px;
}

.card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 600;
}

.provider-alert {
  margin-bottom: 16px;
}

.provider-form {
  max-width: 640px;
}

.hint {
  margin-left: 12px;
  color: #8a97ad;
  font-size: 12px;
}

.test-hint {
  margin-left: 8px;
}
</style>
