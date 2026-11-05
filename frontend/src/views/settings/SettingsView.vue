<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { ApiError } from '@/api/http'
import { fetchCurrentTenant, updateCurrentTenant } from '@/api/tenants'
import { QUOTE_CURRENCY_OPTIONS } from '@/constants/catalog'
import {
  EXPORT_MARKET_SUGGESTIONS,
  LANGUAGE_OPTIONS,
  TENANT_ERROR_MESSAGES,
  TENANT_STATUS_LABELS,
  TENANT_STATUS_TAG,
} from '@/constants/settings'
import AIProviderPanel from './components/AIProviderPanel.vue'
import { useAuthStore } from '@/stores/auth'
import type { TenantProfile, TenantProfileUpdatePayload } from '@/types/tenant'
import { formatDateTime } from '@/utils/format'

const auth = useAuthStore()
const canUpdate = computed(() => auth.hasPermission('tenant:update'))

const profile = ref<TenantProfile | null>(null)
const loading = ref(false)
const saving = ref(false)
const formRef = ref<FormInstance>()

interface SettingsForm {
  name: string
  contact_email: string
  contact_phone: string
  website: string
  address: string
  main_products: string
  export_markets: string[]
  default_currency: string
  default_language: string
}

const form = reactive<SettingsForm>({
  name: '',
  contact_email: '',
  contact_phone: '',
  website: '',
  address: '',
  main_products: '',
  export_markets: [],
  default_currency: 'USD',
  default_language: 'en',
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入企业名称', trigger: 'blur' }],
  contact_email: [{ type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' }],
}

const statusLabel = computed(() =>
  profile.value ? TENANT_STATUS_LABELS[profile.value.status] : '',
)

function applyProfile(data: TenantProfile): void {
  profile.value = data
  form.name = data.name
  form.contact_email = data.contact_email ?? ''
  form.contact_phone = data.contact_phone ?? ''
  form.website = data.website ?? ''
  form.address = data.address ?? ''
  form.main_products = data.main_products ?? ''
  form.export_markets = [...data.export_markets]
  form.default_currency = data.default_currency
  form.default_language = data.default_language
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return TENANT_ERROR_MESSAGES[error.code] ?? error.message
  }
  return '操作失败，请稍后重试'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    applyProfile(await fetchCurrentTenant())
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    loading.value = false
  }
}

function reset(): void {
  if (profile.value) {
    applyProfile(profile.value)
    formRef.value?.clearValidate()
  }
}

async function save(): Promise<void> {
  if (!formRef.value) {
    return
  }
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }

  const payload: TenantProfileUpdatePayload = {
    name: form.name.trim(),
    contact_email: form.contact_email.trim() || null,
    contact_phone: form.contact_phone.trim() || null,
    website: form.website.trim() || null,
    address: form.address.trim() || null,
    main_products: form.main_products.trim() || null,
    export_markets: form.export_markets,
    default_currency: form.default_currency,
    default_language: form.default_language,
  }

  saving.value = true
  try {
    applyProfile(await updateCurrentTenant(payload))
    await auth.loadCurrentUser()
    ElMessage.success('企业资料已保存')
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="settings-page" v-loading="loading && !profile">
    <el-card shadow="never" class="toolbar-card">
      <div class="page-head">
        <div>
          <h2>企业设置</h2>
          <p>维护公司信息、出口市场与默认币种语言，这些默认值会用于报价与邮件。</p>
        </div>
        <div v-if="profile" class="identity">
          <el-tag :type="TENANT_STATUS_TAG[profile.status]" effect="plain">
            {{ statusLabel }}
          </el-tag>
          <span class="slug">企业标识：{{ profile.slug }}</span>
          <span v-if="profile.plan_code" class="slug">套餐：{{ profile.plan_code }}</span>
        </div>
      </div>
    </el-card>

    <el-alert
      v-if="profile && !canUpdate"
      type="info"
      :closable="false"
      show-icon
      title="当前角色仅可查看企业资料，如需修改请联系企业管理员。"
    />

    <el-card v-if="profile" shadow="never" class="form-card">
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="110px"
        :disabled="!canUpdate"
        class="settings-form"
      >
        <el-divider content-position="left">公司信息</el-divider>
        <div class="form-grid">
          <el-form-item label="企业名称" prop="name">
            <el-input v-model="form.name" maxlength="200" show-word-limit />
          </el-form-item>
          <el-form-item label="联系邮箱" prop="contact_email">
            <el-input v-model="form.contact_email" maxlength="320" placeholder="sales@example.com" />
          </el-form-item>
          <el-form-item label="联系电话" prop="contact_phone">
            <el-input v-model="form.contact_phone" maxlength="40" placeholder="+86 574 8888 0000" />
          </el-form-item>
          <el-form-item label="官网" prop="website">
            <el-input v-model="form.website" maxlength="255" placeholder="https://example.com" />
          </el-form-item>
        </div>
        <el-form-item label="公司地址" prop="address">
          <el-input v-model="form.address" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="主营产品" prop="main_products">
          <el-input
            v-model="form.main_products"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="例如：六角螺栓、法兰螺母、自攻螺钉，碳钢与不锈钢材质"
          />
        </el-form-item>

        <el-divider content-position="left">出口与默认设置</el-divider>
        <el-form-item label="出口市场" prop="export_markets">
          <el-select
            v-model="form.export_markets"
            multiple
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="选择或输入出口市场"
            style="width: 100%"
          >
            <el-option
              v-for="market in EXPORT_MARKET_SUGGESTIONS"
              :key="market"
              :label="market"
              :value="market"
            />
          </el-select>
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="默认币种" prop="default_currency">
            <el-select v-model="form.default_currency" style="width: 100%">
              <el-option
                v-for="currency in QUOTE_CURRENCY_OPTIONS"
                :key="currency"
                :label="currency"
                :value="currency"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="默认语言" prop="default_language">
            <el-select v-model="form.default_language" style="width: 100%">
              <el-option
                v-for="language in LANGUAGE_OPTIONS"
                :key="language.value"
                :label="language.label"
                :value="language.value"
              />
            </el-select>
          </el-form-item>
        </div>

        <div v-if="canUpdate" class="actions">
          <el-button @click="reset">重置</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </div>
      </el-form>
      <p class="updated-at">最后更新：{{ formatDateTime(profile?.updated_at) }}</p>
    </el-card>
  <AIProviderPanel />
  </section>
</template>

<style scoped>
.settings-page {
  display: grid;
  gap: 16px;
}

.toolbar-card,
.form-card {
  border-radius: 16px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.page-head h2 {
  margin: 0;
  color: #14213d;
  font-size: 22px;
}

.page-head p {
  margin: 6px 0 0;
  color: #7b879c;
  font-size: 13px;
}

.identity {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  color: #5b6884;
  font-size: 13px;
}

.slug {
  color: #7b879c;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 24px;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}

.updated-at {
  margin: 12px 0 0;
  color: #9aa6b8;
  font-size: 12px;
  text-align: right;
}

@media (max-width: 900px) {
  .form-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
