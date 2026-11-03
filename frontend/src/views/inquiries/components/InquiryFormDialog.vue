<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { fetchCustomers } from '@/api/customers'
import { ApiError } from '@/api/http'
import { createInquiry, updateInquiry } from '@/api/inquiries'
import { INQUIRY_SOURCE_OPTIONS } from '@/constants/catalog'
import type { Customer } from '@/types/customer'
import type {
  InquiryCreatePayload,
  InquiryDetail,
  InquirySourceType,
  InquiryUpdatePayload,
} from '@/types/inquiry'

const props = defineProps<{
  modelValue: boolean
  inquiry?: InquiryDetail | null
  defaultCustomerId?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [inquiry: InquiryDetail]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const formRef = ref<FormInstance>()
const saving = ref(false)
const customers = ref<Customer[]>([])
const customersLoading = ref(false)
const isEdit = computed(() => Boolean(props.inquiry))

const LANGUAGE_OPTIONS = ['EN', 'DE', 'FR', 'ES', 'IT', 'NL', 'PL', 'PT', 'RU', 'AR', 'ZH']

interface InquiryForm {
  customer_id: string
  subject: string
  source_type: InquirySourceType
  source_ref: string
  language: string
  raw_body: string
  received_at: Date | null
}

const form = reactive<InquiryForm>({
  customer_id: '',
  subject: '',
  source_type: 'MANUAL',
  source_ref: '',
  language: '',
  raw_body: '',
  received_at: null,
})

const rules: FormRules = {
  customer_id: [{ required: true, message: '请选择客户', trigger: 'change' }],
  subject: [
    { required: true, message: '请输入询盘主题', trigger: 'blur' },
    { max: 240, message: '主题不能超过 240 个字符', trigger: 'blur' },
  ],
}

async function loadCustomers(): Promise<void> {
  if (customers.value.length > 0) {
    return
  }
  customersLoading.value = true
  try {
    const envelope = await fetchCustomers({ page: 1, page_size: 100 })
    customers.value = envelope.data
  } catch {
    customers.value = []
  } finally {
    customersLoading.value = false
  }
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) {
      return
    }
    await loadCustomers()
    const source = props.inquiry
    form.customer_id = source?.customer_id ?? props.defaultCustomerId ?? ''
    form.subject = source?.subject ?? ''
    form.source_type = source?.source_type ?? 'MANUAL'
    form.source_ref = source?.source_ref ?? ''
    form.language = source?.language ?? ''
    form.raw_body = source?.raw_body ?? ''
    form.received_at = null
    await nextTick()
    formRef.value?.clearValidate()
  },
)

async function submit(): Promise<void> {
  if (!formRef.value) {
    return
  }
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }

  const base = {
    customer_id: form.customer_id,
    subject: form.subject.trim(),
    source_type: form.source_type,
    source_ref: form.source_ref.trim() || null,
    language: form.language.trim().toUpperCase() || null,
    raw_body: form.raw_body.trim() || null,
  }

  saving.value = true
  try {
    let saved: InquiryDetail
    if (props.inquiry) {
      const payload: InquiryUpdatePayload = base
      saved = await updateInquiry(props.inquiry.id, payload)
    } else {
      const payload: InquiryCreatePayload = {
        ...base,
        received_at: form.received_at ? form.received_at.toISOString() : null,
      }
      saved = await createInquiry(payload)
    }
    ElMessage.success(isEdit.value ? '询盘已更新' : '询盘已创建')
    emit('saved', saved)
    visible.value = false
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '保存询盘失败，请稍后重试')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑询盘' : '新建询盘'"
    width="680px"
    :close-on-click-modal="false"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="客户" prop="customer_id">
        <el-select
          v-model="form.customer_id"
          filterable
          clearable
          :loading="customersLoading"
          placeholder="选择客户"
          style="width: 100%"
        >
          <el-option
            v-for="customer in customers"
            :key="customer.id"
            :label="customer.country_code ? `${customer.company_name} · ${customer.country_code}` : customer.company_name"
            :value="customer.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="询盘主题" prop="subject">
        <el-input v-model="form.subject" maxlength="240" placeholder="例如 Hex bolts M10x60 SUS304 inquiry" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="来源" prop="source_type">
            <el-select v-model="form.source_type" style="width: 100%">
              <el-option
                v-for="option in INQUIRY_SOURCE_OPTIONS"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="语言" prop="language">
            <el-select
              v-model="form.language"
              filterable
              allow-create
              default-first-option
              clearable
              placeholder="如 EN"
              style="width: 100%"
            >
              <el-option v-for="code in LANGUAGE_OPTIONS" :key="code" :label="code" :value="code" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="来源编号" prop="source_ref">
            <el-input v-model="form.source_ref" maxlength="255" placeholder="邮件主题 / 消息 ID（可选）" />
          </el-form-item>
        </el-col>
        <el-col v-if="!isEdit" :span="12">
          <el-form-item label="接收时间" prop="received_at">
            <el-date-picker
              v-model="form.received_at"
              type="datetime"
              placeholder="默认当前时间"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="原始内容" prop="raw_body">
        <el-input
          v-model="form.raw_body"
          type="textarea"
          :rows="8"
          maxlength="20000"
          show-word-limit
          placeholder="粘贴客户原始询盘邮件或消息正文，用于 AI 解析产品需求。"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>
