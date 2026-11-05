<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { createProduct, updateProduct } from '@/api/products'
import { ApiError } from '@/api/http'
import {
  CATALOG_STATUS_OPTIONS,
  PRODUCT_CATEGORY_OPTIONS,
} from '@/constants/catalog'
import type {
  CatalogStatus,
  Product,
  ProductCategory,
  ProductPayload,
} from '@/types/product'

const props = defineProps<{
  modelValue: boolean
  product?: Product | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [product: Product]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const formRef = ref<FormInstance>()
const saving = ref(false)
const isEdit = computed(() => Boolean(props.product))
const packagingPlaceholder = '{"carton_qty": 500, "carton_weight_kg": 25}'
const attributesPlaceholder = '{"temperature_range": "-20~80℃"}'

interface ProductForm {
  product_code: string
  product_name: string
  category: ProductCategory
  standard_code: string
  material: string
  grade: string
  diameter: string
  length: string
  thread_pitch: string
  head_type: string
  drive_type: string
  surface_finish: string
  sales_unit: string
  moq: string
  packaging: string
  attributes: string
  status: CatalogStatus
}

const form = reactive<ProductForm>({
  product_code: '',
  product_name: '',
  category: 'BOLT',
  standard_code: '',
  material: '',
  grade: '',
  diameter: '',
  length: '',
  thread_pitch: '',
  head_type: '',
  drive_type: '',
  surface_finish: '',
  sales_unit: 'PCS',
  moq: '',
  packaging: '',
  attributes: '',
  status: 'ACTIVE',
})

function formatJson(value: Record<string, unknown> | null | undefined): string {
  if (!value || Object.keys(value).length === 0) {
    return ''
  }
  return JSON.stringify(value, null, 2)
}

function parseJsonObject(value: string): Record<string, unknown> | null {
  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }
  const parsed: unknown = JSON.parse(trimmed)
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('not an object')
  }
  return parsed as Record<string, unknown>
}

function jsonObjectRule(label: string) {
  return {
    trigger: 'blur' as const,
    validator: (_rule: unknown, value: string) => {
      try {
        parseJsonObject(value)
        return true
      } catch {
        throw new Error(`${label}需为 JSON 对象，例如 {"key": "value"}`)
      }
    },
  }
}

const rules: FormRules = {
  product_code: [
    { required: true, message: '请输入产品编码', trigger: 'blur' },
    { max: 80, message: '产品编码不能超过 80 个字符', trigger: 'blur' },
  ],
  product_name: [
    { required: true, message: '请输入产品名称', trigger: 'blur' },
    { max: 240, message: '产品名称不能超过 240 个字符', trigger: 'blur' },
  ],
  category: [{ required: true, message: '请选择产品品类', trigger: 'change' }],
  sales_unit: [{ required: true, message: '请输入销售单位', trigger: 'blur' }],
  moq: [{ pattern: /^\d+(\.\d+)?$/, message: 'MOQ 需为非负数字', trigger: 'blur' }],
  packaging: [jsonObjectRule('包装信息')],
  attributes: [jsonObjectRule('产品属性')],
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) {
      return
    }
    const product = props.product
    form.product_code = product?.product_code ?? ''
    form.product_name = product?.product_name ?? ''
    form.category = product?.category ?? 'BOLT'
    form.standard_code = product?.standard_code ?? ''
    form.material = product?.material ?? ''
    form.grade = product?.grade ?? ''
    form.diameter = product?.diameter ?? ''
    form.length = product?.length ?? ''
    form.thread_pitch = product?.thread_pitch ?? ''
    form.head_type = product?.head_type ?? ''
    form.drive_type = product?.drive_type ?? ''
    form.surface_finish = product?.surface_finish ?? ''
    form.sales_unit = product?.sales_unit ?? 'PCS'
    form.moq = product?.moq ?? ''
    form.packaging = formatJson(product?.packaging)
    form.attributes = formatJson(product?.attributes)
    form.status = product?.status ?? 'ACTIVE'
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

  const packaging = parseJsonObject(form.packaging)
  const attributes = parseJsonObject(form.attributes) ?? {}
  const payload: ProductPayload = {
    product_code: form.product_code.trim(),
    product_name: form.product_name.trim(),
    category: form.category,
    standard_code: form.standard_code.trim() || null,
    material: form.material.trim() || null,
    grade: form.grade.trim() || null,
    diameter: form.diameter.trim() || null,
    length: form.length.trim() || null,
    thread_pitch: form.thread_pitch.trim() || null,
    head_type: form.head_type.trim() || null,
    drive_type: form.drive_type.trim() || null,
    surface_finish: form.surface_finish.trim() || null,
    sales_unit: form.sales_unit.trim(),
    moq: form.moq.trim() || null,
    packaging,
    attributes,
    status: form.status,
  }

  saving.value = true
  try {
    const saved = props.product
      ? await updateProduct(props.product.id, payload)
      : await createProduct(payload)
    ElMessage.success(isEdit.value ? '产品资料已更新' : '产品已创建')
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
    :title="isEdit ? '编辑产品' : '新建产品'"
    width="760px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
      <div class="form-grid">
        <el-form-item label="产品编码" prop="product_code">
          <el-input v-model="form.product_code" maxlength="80" placeholder="例如 HEX-BOLT-M12-60" />
        </el-form-item>
        <el-form-item label="产品名称" prop="product_name">
          <el-input v-model="form.product_name" maxlength="240" placeholder="六角头螺栓 M12×60" />
        </el-form-item>
        <el-form-item label="品类" prop="category">
          <el-select v-model="form.category" style="width: 100%">
            <el-option
              v-for="option in PRODUCT_CATEGORY_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态" prop="status">
          <el-select v-model="form.status" style="width: 100%">
            <el-option
              v-for="option in CATALOG_STATUS_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="标准号" prop="standard_code">
          <el-input v-model="form.standard_code" maxlength="80" placeholder="DIN 933 / ISO 4017" />
        </el-form-item>
        <el-form-item label="材质" prop="material">
          <el-input v-model="form.material" maxlength="80" placeholder="碳钢 / 不锈钢 304" />
        </el-form-item>
        <el-form-item label="等级" prop="grade">
          <el-input v-model="form.grade" maxlength="80" placeholder="8.8 / A2-70" />
        </el-form-item>
        <el-form-item label="表面处理" prop="surface_finish">
          <el-input v-model="form.surface_finish" maxlength="80" placeholder="镀锌 / 发黑" />
        </el-form-item>
        <el-form-item label="直径" prop="diameter">
          <el-input v-model="form.diameter" maxlength="40" placeholder="M12" />
        </el-form-item>
        <el-form-item label="长度" prop="length">
          <el-input v-model="form.length" maxlength="40" placeholder="60mm" />
        </el-form-item>
        <el-form-item label="螺距" prop="thread_pitch">
          <el-input v-model="form.thread_pitch" maxlength="40" placeholder="1.75mm" />
        </el-form-item>
        <el-form-item label="头型" prop="head_type">
          <el-input v-model="form.head_type" maxlength="80" placeholder="六角头 / 内六角" />
        </el-form-item>
        <el-form-item label="驱动方式" prop="drive_type">
          <el-input v-model="form.drive_type" maxlength="80" placeholder="外六角 / 内六角" />
        </el-form-item>
        <el-form-item label="销售单位" prop="sales_unit">
          <el-input v-model="form.sales_unit" maxlength="20" placeholder="PCS / KG / SET" />
        </el-form-item>
        <el-form-item label="MOQ" prop="moq">
          <el-input v-model="form.moq" placeholder="例如 1000" style="width: 160px" />
        </el-form-item>
      </div>

      <el-form-item label="包装信息" prop="packaging">
        <el-input
          v-model="form.packaging"
          type="textarea"
          :rows="3"
          :placeholder="packagingPlaceholder"
        />
      </el-form-item>
      <el-form-item label="产品属性" prop="attributes">
        <el-input
          v-model="form.attributes"
          type="textarea"
          :rows="3"
          :placeholder="attributesPlaceholder"
        />
      </el-form-item>
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
