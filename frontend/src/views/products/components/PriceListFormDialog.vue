<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { createPriceList, updatePriceList } from '@/api/priceLists'
import { ApiError } from '@/api/http'
import { CATALOG_STATUS_OPTIONS } from '@/constants/catalog'
import type { CatalogStatus, PriceList, PriceListDetail } from '@/types/product'

const props = defineProps<{
  modelValue: boolean
  priceList?: PriceList | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [priceList: PriceListDetail]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const formRef = ref<FormInstance>()
const saving = ref(false)
const isEdit = computed(() => Boolean(props.priceList))

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

interface PriceListForm {
  name: string
  currency: string
  valid_from: string
  valid_to: string
  status: CatalogStatus
  version: number
}

const form = reactive<PriceListForm>({
  name: '',
  currency: 'USD',
  valid_from: today(),
  valid_to: '',
  status: 'ACTIVE',
  version: 1,
})

const rules: FormRules = {
  name: [
    { required: true, message: '请输入价格表名称', trigger: 'blur' },
    { max: 160, message: '名称不能超过 160 个字符', trigger: 'blur' },
  ],
  currency: [
    { required: true, message: '请输入币种', trigger: 'blur' },
    { pattern: /^[A-Za-z]{3}$/, message: '请输入三位币种代码，如 USD', trigger: 'blur' },
  ],
  valid_from: [{ required: true, message: '请选择生效日期', trigger: 'change' }],
  valid_to: [
    {
      trigger: 'change',
      validator: (_rule: unknown, value: string) => {
        if (value && form.valid_from && value < form.valid_from) {
          throw new Error('失效日期不能早于生效日期')
        }
        return true
      },
    },
  ],
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) {
      return
    }
    form.name = props.priceList?.name ?? ''
    form.currency = props.priceList?.currency ?? 'USD'
    form.valid_from = props.priceList?.valid_from ?? today()
    form.valid_to = props.priceList?.valid_to ?? ''
    form.status = props.priceList?.status ?? 'ACTIVE'
    form.version = props.priceList?.version ?? 1
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

  saving.value = true
  try {
    const saved = props.priceList
      ? await updatePriceList(props.priceList.id, {
          name: form.name.trim(),
          valid_to: form.valid_to || null,
          status: form.status,
        })
      : await createPriceList({
          name: form.name.trim(),
          currency: form.currency.trim().toUpperCase(),
          valid_from: form.valid_from,
          valid_to: form.valid_to || null,
          status: form.status,
          version: form.version,
        })
    ElMessage.success(isEdit.value ? '价格表信息已更新' : '价格表已创建')
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
    :title="isEdit ? '编辑价格表' : '新建价格表'"
    width="540px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" maxlength="160" placeholder="例如 2026 年外销基准价" />
      </el-form-item>
      <el-form-item label="币种" prop="currency">
        <el-input
          v-model="form.currency"
          maxlength="3"
          :disabled="isEdit"
          placeholder="USD"
          style="width: 140px"
        />
      </el-form-item>
      <el-form-item label="生效日期" prop="valid_from">
        <el-date-picker
          v-model="form.valid_from"
          type="date"
          value-format="YYYY-MM-DD"
          :disabled="isEdit"
          placeholder="选择日期"
          style="width: 180px"
        />
      </el-form-item>
      <el-form-item label="失效日期" prop="valid_to">
        <el-date-picker
          v-model="form.valid_to"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="留空表示长期"
          style="width: 180px"
        />
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-select v-model="form.status" style="width: 180px">
          <el-option
            v-for="option in CATALOG_STATUS_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item v-if="!isEdit" label="版本" prop="version">
        <el-input-number v-model="form.version" :min="1" :step="1" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>
