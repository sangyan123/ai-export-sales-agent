<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { createCustomer, updateCustomer } from '@/api/customers'
import { ApiError } from '@/api/http'
import { CUSTOMER_STATUS_OPTIONS } from '@/constants/catalog'
import type { Customer, CustomerPayload, CustomerStatus } from '@/types/customer'

const props = defineProps<{
  modelValue: boolean
  customer?: Customer | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [customer: Customer]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const formRef = ref<FormInstance>()
const saving = ref(false)
const isEdit = computed(() => Boolean(props.customer))
// 放在脚本里绑定：模板内联字符串中的 "//" 会被 vue-tsc 代码生成错误转义
const websitePlaceholder = 'https://example.com'

interface CustomerForm {
  company_name: string
  country_code: string
  website: string
  source: string
  status: CustomerStatus
}

const form = reactive<CustomerForm>({
  company_name: '',
  country_code: '',
  website: '',
  source: '',
  status: 'ACTIVE',
})

const rules: FormRules = {
  company_name: [
    { required: true, message: '请输入公司名称', trigger: 'blur' },
    { max: 240, message: '公司名称不能超过 240 个字符', trigger: 'blur' },
  ],
  country_code: [
    { pattern: /^[A-Za-z]{2}$/, message: '请输入两位国家代码，如 US、DE', trigger: 'blur' },
  ],
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) {
      return
    }
    form.company_name = props.customer?.company_name ?? ''
    form.country_code = props.customer?.country_code ?? ''
    form.website = props.customer?.website ?? ''
    form.source = props.customer?.source ?? ''
    form.status = props.customer?.status ?? 'ACTIVE'
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

  const payload: CustomerPayload = {
    company_name: form.company_name.trim(),
    country_code: form.country_code.trim().toUpperCase() || null,
    website: form.website.trim() || null,
    source: form.source.trim() || null,
    status: form.status,
  }

  saving.value = true
  try {
    const saved = props.customer
      ? await updateCustomer(props.customer.id, payload)
      : await createCustomer(payload)
    ElMessage.success(isEdit.value ? '客户资料已更新' : '客户已创建')
    emit('saved', saved)
    visible.value = false
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '保存失败，请稍后重试')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑客户' : '新建客户'"
    width="540px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="公司名称" prop="company_name">
        <el-input v-model="form.company_name" maxlength="240" placeholder="例如 Acme Fasteners GmbH" />
      </el-form-item>
      <el-form-item label="国家代码" prop="country_code">
        <el-input
          v-model="form.country_code"
          maxlength="2"
          placeholder="ISO 3166-1，如 DE"
          style="width: 180px"
        />
      </el-form-item>
      <el-form-item label="网站" prop="website">
        <el-input v-model="form.website" maxlength="255" :placeholder="websitePlaceholder" />
      </el-form-item>
      <el-form-item label="来源" prop="source">
        <el-input v-model="form.source" maxlength="40" placeholder="展会 / 阿里国际站 / 转介绍" />
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-select v-model="form.status" style="width: 180px">
          <el-option
            v-for="option in CUSTOMER_STATUS_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>
