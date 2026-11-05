<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { fetchCustomers } from '@/api/customers'
import { createFollowup, followupErrorMessage, updateFollowup } from '@/api/followups'
import { fetchInquiries } from '@/api/inquiries'
import type { Customer } from '@/types/customer'
import type { FollowupTask } from '@/types/followup'
import type { InquirySummary } from '@/types/inquiry'

const props = defineProps<{
  modelValue: boolean
  task?: FollowupTask | null
  defaultCustomerId?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [task: FollowupTask]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const formRef = ref<FormInstance>()
const saving = ref(false)
const customers = ref<Customer[]>([])
const inquiries = ref<InquirySummary[]>([])
const customersLoading = ref(false)
const inquiriesLoading = ref(false)
const isEdit = computed(() => Boolean(props.task))

interface FollowupForm {
  customer_id: string
  inquiry_id: string
  title: string
  due_at: Date | null
}

const form = reactive<FollowupForm>({
  customer_id: '',
  inquiry_id: '',
  title: '',
  due_at: null,
})

const rules: FormRules = {
  customer_id: [{ required: true, message: '请选择客户', trigger: 'change' }],
  title: [
    { required: true, message: '请输入跟进内容', trigger: 'blur' },
    { max: 240, message: '跟进内容不能超过 240 个字符', trigger: 'blur' },
  ],
  due_at: [{ required: true, message: '请选择到期时间', trigger: 'change' }],
}

const inquiryOptions = computed(() =>
  inquiries.value.filter((inquiry) => inquiry.customer_id === form.customer_id),
)

function customerLabel(customer: Customer): string {
  return customer.country_code ? `${customer.company_name} · ${customer.country_code}` : customer.company_name
}

function inquiryLabel(inquiry: InquirySummary): string {
  return inquiry.subject || inquiry.id.slice(0, 8)
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

async function loadInquiries(): Promise<void> {
  if (inquiries.value.length > 0) {
    return
  }
  inquiriesLoading.value = true
  try {
    const envelope = await fetchInquiries({ page: 1, page_size: 100 })
    inquiries.value = envelope.data
  } catch {
    inquiries.value = []
  } finally {
    inquiriesLoading.value = false
  }
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) {
      return
    }
    await Promise.all([loadCustomers(), loadInquiries()])
    const source = props.task
    form.customer_id = source?.customer_id ?? props.defaultCustomerId ?? ''
    form.inquiry_id = source?.inquiry_id ?? ''
    form.title = source?.title ?? ''
    form.due_at = source ? new Date(source.due_at) : null
    await nextTick()
    formRef.value?.clearValidate()
  },
)

watch(
  () => form.customer_id,
  () => {
    if (form.inquiry_id && !inquiryOptions.value.some((item) => item.id === form.inquiry_id)) {
      form.inquiry_id = ''
    }
  },
)

async function submit(): Promise<void> {
  if (!formRef.value || !form.due_at) {
    return
  }
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }

  saving.value = true
  try {
    const base = {
      title: form.title.trim(),
      due_at: form.due_at.toISOString(),
    }
    const saved = props.task
      ? await updateFollowup(props.task.id, base)
      : await createFollowup({
          ...base,
          customer_id: form.customer_id,
          inquiry_id: form.inquiry_id || null,
        })
    ElMessage.success(isEdit.value ? '跟进任务已更新' : '跟进任务已创建')
    emit('saved', saved)
    visible.value = false
  } catch (error) {
    ElMessage.error(followupErrorMessage(error, '保存跟进任务失败，请稍后重试'))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑跟进任务' : '新建跟进任务'"
    width="620px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="客户" prop="customer_id">
        <el-select
          v-model="form.customer_id"
          filterable
          :disabled="isEdit"
          :loading="customersLoading"
          placeholder="选择客户"
          style="width: 100%"
        >
          <el-option
            v-for="customer in customers"
            :key="customer.id"
            :label="customerLabel(customer)"
            :value="customer.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="关联询盘">
        <el-select
          v-model="form.inquiry_id"
          filterable
          clearable
          :disabled="!form.customer_id"
          :loading="inquiriesLoading"
          placeholder="可选，仅显示该客户的询盘"
          style="width: 100%"
        >
          <el-option
            v-for="inquiry in inquiryOptions"
            :key="inquiry.id"
            :label="inquiryLabel(inquiry)"
            :value="inquiry.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="跟进内容" prop="title">
        <el-input
          v-model="form.title"
          maxlength="240"
          show-word-limit
          placeholder="例如：回访报价反馈并确认交期"
        />
      </el-form-item>
      <el-form-item label="到期时间" prop="due_at">
        <el-date-picker
          v-model="form.due_at"
          type="datetime"
          placeholder="选择到期时间"
          style="width: 100%"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>
