<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { createPriceTier, updatePriceTier } from '@/api/priceLists'
import { ApiError } from '@/api/http'
import { PRICE_BASIS_OPTIONS } from '@/constants/catalog'
import type { PriceBasis, PriceTier, ProductSummary } from '@/types/product'

const props = defineProps<{
  modelValue: boolean
  priceListId: string
  tier?: PriceTier | null
  products: ProductSummary[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: []
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const formRef = ref<FormInstance>()
const saving = ref(false)
const isEdit = computed(() => Boolean(props.tier))

interface TierForm {
  product_id: string
  min_quantity: string
  max_quantity: string
  unit_price: string
  price_basis: PriceBasis
  unit: string
  valid_from: string
  valid_to: string
}

const form = reactive<TierForm>({
  product_id: '',
  min_quantity: '',
  max_quantity: '',
  unit_price: '',
  price_basis: 'PER_PIECE',
  unit: '',
  valid_from: '',
  valid_to: '',
})

const rules: FormRules = {
  product_id: [{ required: true, message: '请选择产品', trigger: 'change' }],
  min_quantity: [
    { required: true, message: '请输入最小数量', trigger: 'blur' },
    { pattern: /^\d+(\.\d{1,4})?$/, message: '数量需为非负数字', trigger: 'blur' },
  ],
  max_quantity: [
    {
      trigger: 'blur',
      validator: (_rule: unknown, value: string) => {
        if (!value) {
          return true
        }
        if (!/^\d+(\.\d{1,4})?$/.test(value)) {
          throw new Error('数量需为非负数字')
        }
        if (form.min_quantity && Number(value) <= Number(form.min_quantity)) {
          throw new Error('最大数量需大于最小数量')
        }
        return true
      },
    },
  ],
  unit_price: [
    { required: true, message: '请输入单价', trigger: 'blur' },
    { pattern: /^\d+(\.\d{1,6})?$/, message: '单价格式如 1.235', trigger: 'blur' },
  ],
  unit: [{ required: true, message: '请输入计价单位', trigger: 'blur' }],
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

function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return '保存失败，请稍后重试'
  }
  if (error.code === 'PRICE_TIER_OVERLAP') {
    return '阶梯数量区间与现有阶梯重叠，请调整数量区间或有效期'
  }
  if (error.code === 'PRICE_TIER_RANGE_INVALID') {
    return '阶梯数量或有效期区间不合法，请检查后重试'
  }
  return error.message
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) {
      return
    }
    form.product_id = props.tier?.product_id ?? ''
    form.min_quantity = props.tier?.min_quantity ?? ''
    form.max_quantity = props.tier?.max_quantity ?? ''
    form.unit_price = props.tier?.unit_price ?? ''
    form.price_basis = props.tier?.price_basis ?? 'PER_PIECE'
    form.unit = props.tier?.unit ?? ''
    form.valid_from = props.tier?.valid_from ?? ''
    form.valid_to = props.tier?.valid_to ?? ''
    await nextTick()
    formRef.value?.clearValidate()
  },
)

function handleProductChange(productId: string): void {
  const product = props.products.find((item) => item.id === productId)
  if (product) {
    form.unit = product.sales_unit
  }
}

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
    const payload = {
      min_quantity: form.min_quantity.trim(),
      max_quantity: form.max_quantity.trim() || null,
      unit_price: form.unit_price.trim(),
      price_basis: form.price_basis,
      unit: form.unit.trim(),
      valid_from: form.valid_from || null,
      valid_to: form.valid_to || null,
    }
    if (props.tier) {
      await updatePriceTier(props.tier.id, payload)
      ElMessage.success('阶梯价已更新')
    } else {
      await createPriceTier(props.priceListId, {
        product_id: form.product_id,
        ...payload,
      })
      ElMessage.success('阶梯价已添加')
    }
    emit('saved')
    visible.value = false
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? '编辑阶梯价' : '新增阶梯价'"
    width="600px"
    :close-on-click-modal="false"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
      <el-form-item label="产品" prop="product_id">
        <el-select
          v-model="form.product_id"
          filterable
          :disabled="isEdit"
          placeholder="搜索产品编码或名称"
          style="width: 100%"
          @change="handleProductChange"
        >
          <el-option
            v-for="product in products"
            :key="product.id"
            :label="`${product.product_code} · ${product.product_name}`"
            :value="product.id"
          />
        </el-select>
      </el-form-item>
      <div class="form-grid">
        <el-form-item label="最小数量" prop="min_quantity">
          <el-input v-model="form.min_quantity" placeholder="例如 1000" />
        </el-form-item>
        <el-form-item label="最大数量" prop="max_quantity">
          <el-input v-model="form.max_quantity" placeholder="留空表示无上限" />
        </el-form-item>
        <el-form-item label="单价" prop="unit_price">
          <el-input v-model="form.unit_price" placeholder="例如 1.235" />
        </el-form-item>
        <el-form-item label="计价方式" prop="price_basis">
          <el-select v-model="form.price_basis" style="width: 100%">
            <el-option
              v-for="option in PRICE_BASIS_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="计价单位" prop="unit">
          <el-input v-model="form.unit" maxlength="20" placeholder="PCS / KG / SET" />
        </el-form-item>
        <el-form-item label="生效日期" prop="valid_from">
          <el-date-picker
            v-model="form.valid_from"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="留空表示长期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="失效日期" prop="valid_to">
          <el-date-picker
            v-model="form.valid_to"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="留空表示长期"
            style="width: 100%"
          />
        </el-form-item>
      </div>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 20px;
}
</style>
