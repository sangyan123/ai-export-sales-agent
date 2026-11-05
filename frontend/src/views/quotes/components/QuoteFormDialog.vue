<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchCustomers } from '@/api/customers'
import { fetchInquiries } from '@/api/inquiries'
import { fetchProducts } from '@/api/products'
import { createQuote, quoteErrorMessage } from '@/api/quotes'
import {
  INQUIRY_STATUS_LABELS,
  QUOTE_CURRENCY_OPTIONS,
} from '@/constants/catalog'
import type { Customer } from '@/types/customer'
import type { InquirySummary } from '@/types/inquiry'
import type { ProductSummary } from '@/types/product'
import type { QuoteCreatePayload, QuoteDetail, QuoteLineCreatePayload } from '@/types/quote'

const props = defineProps<{ modelValue: boolean }>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [quote: QuoteDetail]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const INCOTERM_OPTIONS = ['EXW', 'FOB', 'CFR', 'CIF', 'DAP', 'DDP']

interface LineForm {
  product_id: string
  quantity: string
  unit: string
}

const saving = ref(false)
const customers = ref<Customer[]>([])
const inquiries = ref<InquirySummary[]>([])
const products = ref<ProductSummary[]>([])
const customersLoading = ref(false)
const inquiriesLoading = ref(false)
const productsLoading = ref(false)

const form = reactive({
  customer_id: '',
  inquiry_id: '',
  currency: 'USD',
  quote_no: '',
  valid_until: '',
  price_as_of: '',
  incoterm: '',
  payment_terms: '',
  lead_time: '',
  discount_total: '',
  freight_total: '',
  other_charges: '',
})

const lines = ref<LineForm[]>([emptyLine()])

function emptyLine(): LineForm {
  return { product_id: '', quantity: '', unit: '' }
}

function productLabel(product: ProductSummary): string {
  const specs = [product.material, product.grade].filter(Boolean).join(' / ')
  return `${product.product_code} · ${product.product_name}${specs ? `（${specs}）` : ''}`
}

function productOptions(): ProductSummary[] {
  return products.value
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

async function loadProducts(): Promise<void> {
  if (products.value.length > 0) {
    return
  }
  productsLoading.value = true
  try {
    const envelope = await fetchProducts({ page: 1, page_size: 100, status: 'ACTIVE' })
    products.value = envelope.data
  } catch {
    products.value = []
  } finally {
    productsLoading.value = false
  }
}

function resetForm(): void {
  form.customer_id = ''
  form.inquiry_id = ''
  form.currency = 'USD'
  form.quote_no = ''
  form.valid_until = ''
  form.price_as_of = ''
  form.incoterm = ''
  form.payment_terms = ''
  form.lead_time = ''
  form.discount_total = ''
  form.freight_total = ''
  form.other_charges = ''
  lines.value = [emptyLine()]
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) {
      return
    }
    resetForm()
    void Promise.all([loadCustomers(), loadInquiries(), loadProducts()])
  },
)

function handleInquiryChange(): void {
  const inquiry = inquiries.value.find((item) => item.id === form.inquiry_id)
  if (inquiry) {
    form.customer_id = inquiry.customer_id
  }
}

function handleProductChange(line: LineForm): void {
  const product = products.value.find((item) => item.id === line.product_id)
  if (product) {
    line.unit = product.sales_unit
  }
}

function addLine(): void {
  lines.value.push(emptyLine())
}

function removeLine(index: number): void {
  if (lines.value.length <= 1) {
    return
  }
  lines.value.splice(index, 1)
}

function buildPayload(): QuoteCreatePayload | null {
  const currency = form.currency.trim().toUpperCase()
  if (!/^[A-Z]{3}$/.test(currency)) {
    ElMessage.warning('币种必须是 3 位字母代码，如 USD')
    return null
  }
  if (!lines.value.length) {
    ElMessage.warning('请至少添加一个报价行项目')
    return null
  }

  const items: QuoteLineCreatePayload[] = []
  for (const [index, line] of lines.value.entries()) {
    const quantity = line.quantity.trim()
    const numeric = Number(quantity)
    if (!line.product_id) {
      ElMessage.warning(`第 ${index + 1} 行请选择产品`)
      return null
    }
    if (!quantity || Number.isNaN(numeric) || numeric <= 0) {
      ElMessage.warning(`第 ${index + 1} 行数量必须大于 0`)
      return null
    }
    if (!line.unit.trim()) {
      ElMessage.warning(`第 ${index + 1} 行请填写单位`)
      return null
    }
    items.push({
      product_id: line.product_id,
      quantity,
      unit: line.unit.trim(),
    })
  }

  const quoteNo = form.quote_no.trim()
  if (quoteNo.length > 40) {
    ElMessage.warning('报价编号不能超过 40 个字符')
    return null
  }

  const discountTotal = form.discount_total.trim()
  const freightTotal = form.freight_total.trim()
  const otherCharges = form.other_charges.trim()
  for (const [label, raw] of [
    ['折扣金额', discountTotal],
    ['运费', freightTotal],
    ['其他费用', otherCharges],
  ] as const) {
    if (!raw) {
      continue
    }
    const numeric = Number(raw)
    if (Number.isNaN(numeric) || numeric < 0) {
      ElMessage.warning(`${label}必须是不小于 0 的数字`)
      return null
    }
  }

  const terms: Record<string, unknown> = {}
  if (form.incoterm.trim()) {
    terms.incoterm = form.incoterm.trim()
  }
  if (form.payment_terms.trim()) {
    terms.payment_terms = form.payment_terms.trim()
  }
  if (form.lead_time.trim()) {
    terms.lead_time = form.lead_time.trim()
  }

  return {
    currency,
    items,
    inquiry_id: form.inquiry_id || null,
    customer_id: form.customer_id || null,
    quote_no: quoteNo || null,
    valid_until: form.valid_until || null,
    price_as_of: form.price_as_of || null,
    discount_total: discountTotal || '0',
    freight_total: freightTotal || '0',
    other_charges: otherCharges || '0',
    terms,
  }
}

async function submit(): Promise<void> {
  const payload = buildPayload()
  if (!payload) {
    return
  }

  saving.value = true
  try {
    const quote = await createQuote(payload)
    ElMessage.success(`报价 ${quote.quote_no} 已创建`)
    emit('created', quote)
    visible.value = false
  } catch (error) {
    ElMessage.error(quoteErrorMessage(error, '创建报价失败，请稍后重试'))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="新建报价"
    width="880px"
    destroy-on-close
  >
    <el-form :model="form" label-width="100px">
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="客户">
            <el-select
              v-model="form.customer_id"
              filterable
              clearable
              :loading="customersLoading"
              placeholder="选择客户（用于客户专属价）"
              style="width: 100%"
            >
              <el-option
                v-for="customer in customers"
                :key="customer.id"
                :label="
                  customer.country_code
                    ? `${customer.company_name} · ${customer.country_code}`
                    : customer.company_name
                "
                :value="customer.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="关联询盘">
            <el-select
              v-model="form.inquiry_id"
              filterable
              clearable
              :loading="inquiriesLoading"
              placeholder="可选，关联询盘后联动状态"
              style="width: 100%"
              @change="handleInquiryChange"
            >
              <el-option
                v-for="inquiry in inquiries"
                :key="inquiry.id"
                :label="`${inquiry.subject} · ${INQUIRY_STATUS_LABELS[inquiry.status]}`"
                :value="inquiry.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>

      <el-row :gutter="12">
        <el-col :span="8">
          <el-form-item label="币种">
            <el-select
              v-model="form.currency"
              filterable
              allow-create
              default-first-option
              style="width: 100%"
            >
              <el-option
                v-for="code in QUOTE_CURRENCY_OPTIONS"
                :key="code"
                :label="code"
                :value="code"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="报价编号">
            <el-input v-model="form.quote_no" maxlength="40" placeholder="留空自动生成" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="有效期至">
            <el-date-picker
              v-model="form.valid_until"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="可选"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="价格基准日">
        <el-date-picker
          v-model="form.price_as_of"
          type="date"
          value-format="YYYY-MM-DD"
          placeholder="默认按今天取价"
          style="width: 280px"
        />
        <span class="hint">按该日期匹配有效价格表、阶梯价与客户专属价。</span>
      </el-form-item>

      <div class="lines-head">
        <span class="lines-title">报价行项目</span>
        <el-button text type="primary" :icon="Plus" @click="addLine">添加行</el-button>
      </div>

      <el-alert
        v-if="!productsLoading && products.length === 0"
        type="warning"
        :closable="false"
        show-icon
        title="暂无可售产品，请先在产品中心维护产品与有效价格。"
        class="products-alert"
      />

      <el-table :data="lines" class="lines-table">
        <el-table-column label="产品" min-width="300">
          <template #default="{ row }">
            <el-select
              v-model="row.product_id"
              filterable
              :loading="productsLoading"
              placeholder="选择产品"
              style="width: 100%"
              @change="handleProductChange(row)"
            >
              <el-option
                v-for="product in productOptions()"
                :key="product.id"
                :label="productLabel(product)"
                :value="product.id"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="数量" width="150">
          <template #default="{ row }">
            <el-input v-model="row.quantity" placeholder="5000" />
          </template>
        </el-table-column>
        <el-table-column label="单位" width="120">
          <template #default="{ row }">
            <el-input v-model="row.unit" maxlength="20" placeholder="PCS" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ $index }">
            <el-button
              link
              type="danger"
              :disabled="lines.length <= 1"
              @click="removeLine($index)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-divider content-position="left">价格与费用（{{ form.currency }}）</el-divider>
      <el-row :gutter="12">
        <el-col :span="8">
          <el-form-item label="折扣金额">
            <el-input v-model="form.discount_total" placeholder="0.00" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="运费">
            <el-input v-model="form.freight_total" placeholder="0.00" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="其他费用">
            <el-input v-model="form.other_charges" placeholder="0.00" />
          </el-form-item>
        </el-col>
      </el-row>
      <p class="amount-hint">
        折扣不能超过报价小计；超过企业折扣上限的报价可以保存草稿，但无法提交审批。
      </p>

      <el-row :gutter="12" class="terms-row">
        <el-col :span="8">
          <el-form-item label="贸易条款">
            <el-select
              v-model="form.incoterm"
              filterable
              allow-create
              clearable
              default-first-option
              placeholder="如 FOB"
              style="width: 100%"
            >
              <el-option
                v-for="term in INCOTERM_OPTIONS"
                :key="term"
                :label="term"
                :value="term"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="付款方式">
            <el-input v-model="form.payment_terms" maxlength="120" placeholder="如 T/T 30% 预付" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="交货期">
            <el-input v-model="form.lead_time" maxlength="120" placeholder="如 25 天" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="报价按价格基准日的有效价格生成；草稿可在详情页重新计算，提交审批后不可重算。"
      />
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">创建报价</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.lines-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 8px 0 10px;
}

.lines-title {
  color: #14213d;
  font-size: 14px;
  font-weight: 600;
}

.lines-table {
  margin-bottom: 18px;
}

.products-alert {
  margin-bottom: 12px;
}

.terms-row {
  margin-top: 4px;
}

.amount-hint {
  margin: -6px 0 14px;
  color: #8a97ad;
  font-size: 12px;
}

.hint {
  margin-left: 12px;
  color: #8a97ad;
  font-size: 12px;
}
</style>
