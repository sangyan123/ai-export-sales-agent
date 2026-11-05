<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import {
  approvePriceOverride,
  createPriceOverride,
  fetchPriceOverrides,
  rejectPriceOverride,
} from '@/api/customers'
import { ApiError } from '@/api/http'
import { fetchProducts, type ProductSummary } from '@/api/products'
import {
  APPROVAL_STATUS_LABELS,
  APPROVAL_STATUS_TAG,
  PRICE_BASIS_LABELS,
  PRICE_BASIS_OPTIONS,
} from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type { OverrideApprovalStatus, PriceBasis, PriceOverride } from '@/types/customer'

const props = defineProps<{ customerId: string }>()

const auth = useAuthStore()
const rows = ref<PriceOverride[]>([])
const products = ref<ProductSummary[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const actionId = ref('')
const formRef = ref<FormInstance>()

const canEdit = computed(() => auth.hasPermission('customer:update'))
const canApprove = computed(() => auth.hasPermission('pricing:update'))
const productMap = computed(() => new Map(products.value.map((item) => [item.id, item])))

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

const form = reactive({
  product_id: '',
  currency: 'USD',
  unit_price: '',
  price_basis: 'PER_PIECE' as PriceBasis,
  unit: '',
  valid_from: today(),
  valid_to: '',
})

const rules: FormRules = {
  product_id: [{ required: true, message: '请选择产品', trigger: 'change' }],
  currency: [
    { required: true, message: '请输入币种', trigger: 'blur' },
    { pattern: /^[A-Za-z]{3}$/, message: '请输入三位币种代码，如 USD', trigger: 'blur' },
  ],
  unit_price: [
    { required: true, message: '请输入单价', trigger: 'blur' },
    { pattern: /^\d+(\.\d{1,4})?$/, message: '单价格式如 1.2350', trigger: 'blur' },
  ],
  unit: [{ required: true, message: '请输入计价单位', trigger: 'blur' }],
  valid_from: [{ required: true, message: '请选择生效日期', trigger: 'change' }],
}

function productLabel(productId: string): string {
  const product = productMap.value.get(productId)
  return product ? `${product.product_code} · ${product.product_name}` : productId
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [overrideEnvelope, productEnvelope] = await Promise.all([
      fetchPriceOverrides(props.customerId, { page_size: 100 }),
      fetchProducts({ page_size: 100, status: 'ACTIVE' }),
    ])
    rows.value = overrideEnvelope.data
    products.value = productEnvelope.data
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载专属价失败')
  } finally {
    loading.value = false
  }
}

async function openDialog(): Promise<void> {
  form.product_id = ''
  form.currency = 'USD'
  form.unit_price = ''
  form.price_basis = 'PER_PIECE'
  form.unit = ''
  form.valid_from = today()
  form.valid_to = ''
  dialogVisible.value = true
  await nextTick()
  formRef.value?.clearValidate()
}

function handleProductChange(productId: string): void {
  const product = productMap.value.get(productId)
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
    await createPriceOverride(props.customerId, {
      product_id: form.product_id,
      currency: form.currency.trim().toUpperCase(),
      unit_price: form.unit_price.trim(),
      price_basis: form.price_basis,
      unit: form.unit.trim(),
      valid_from: form.valid_from,
      valid_to: form.valid_to || null,
    })
    ElMessage.success('专属价已提交，等待审批')
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '提交专属价失败')
  } finally {
    saving.value = false
  }
}

async function approve(row: PriceOverride): Promise<void> {
  try {
    await ElMessageBox.confirm('通过后该价格将在有效期内生效，是否继续？', '审批专属价', {
      type: 'warning',
      confirmButtonText: '通过',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  actionId.value = row.id
  try {
    await approvePriceOverride(props.customerId, row.id)
    ElMessage.success('专属价已通过')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '审批失败')
  } finally {
    actionId.value = ''
  }
}

async function reject(row: PriceOverride): Promise<void> {
  try {
    await ElMessageBox.confirm('确认驳回该专属价申请？', '驳回专属价', {
      type: 'warning',
      confirmButtonText: '驳回',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  actionId.value = row.id
  try {
    await rejectPriceOverride(props.customerId, row.id)
    ElMessage.success('专属价已驳回')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '驳回失败')
  } finally {
    actionId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <div class="panel-toolbar">
      <span class="hint">专属价按客户 + 产品 + 币种生效，同一生效日期只能有一条记录。</span>
      <el-button v-if="canEdit" type="primary" :icon="Plus" size="small" @click="openDialog">
        新增专属价
      </el-button>
    </div>

    <el-table v-loading="loading" :data="rows" row-key="id">
      <el-table-column label="产品" min-width="240">
        <template #default="{ row }">{{ productLabel(row.product_id) }}</template>
      </el-table-column>
      <el-table-column label="专属单价" min-width="160">
        <template #default="{ row }">
          <strong class="price">{{ row.currency }} {{ row.unit_price }}</strong>
          <span class="unit">/ {{ row.unit }}</span>
        </template>
      </el-table-column>
      <el-table-column label="计价方式" width="110" align="center">
        <template #default="{ row }">{{ PRICE_BASIS_LABELS[row.price_basis as PriceBasis] }}</template>
      </el-table-column>
      <el-table-column label="有效期" min-width="210">
        <template #default="{ row }">
          {{ row.valid_from }} 至 {{ row.valid_to || '长期' }}
        </template>
      </el-table-column>
      <el-table-column label="审批状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag
            :type="APPROVAL_STATUS_TAG[row.approval_status as OverrideApprovalStatus]"
            effect="plain"
          >
            {{ APPROVAL_STATUS_LABELS[row.approval_status as OverrideApprovalStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="canApprove" label="操作" width="140" align="center">
        <template #default="{ row }">
          <template v-if="row.approval_status === 'PENDING'">
            <el-button
              link
              type="primary"
              :loading="actionId === row.id"
              @click="approve(row)"
            >
              通过
            </el-button>
            <el-button link type="danger" :disabled="actionId === row.id" @click="reject(row)">
              驳回
            </el-button>
          </template>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无专属价，新增后需审批才会生效" />
      </template>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      title="新增专属价"
      width="560px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="产品" prop="product_id">
          <el-select
            v-model="form.product_id"
            filterable
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
        <el-form-item label="币种" prop="currency">
          <el-input v-model="form.currency" maxlength="3" style="width: 120px" />
        </el-form-item>
        <el-form-item label="单价" prop="unit_price">
          <el-input v-model="form.unit_price" placeholder="例如 1.2350" style="width: 180px" />
        </el-form-item>
        <el-form-item label="计价方式" prop="price_basis">
          <el-select v-model="form.price_basis" style="width: 180px">
            <el-option
              v-for="option in PRICE_BASIS_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="计价单位" prop="unit">
          <el-input v-model="form.unit" maxlength="20" placeholder="PCS / KG / SET" style="width: 180px" />
        </el-form-item>
        <el-form-item label="生效日期" prop="valid_from">
          <el-date-picker
            v-model="form.valid_from"
            type="date"
            value-format="YYYY-MM-DD"
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
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">提交审批</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.panel {
  display: grid;
  gap: 12px;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hint {
  color: #8a97ad;
  font-size: 12px;
}

.price {
  color: #14213d;
}

.unit {
  margin-left: 4px;
  color: #8a97ad;
  font-size: 12px;
}

.muted {
  color: #9aa6b8;
}
</style>
