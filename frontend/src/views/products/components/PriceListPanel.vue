<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchProducts } from '@/api/products'
import { fetchPriceList, fetchPriceLists } from '@/api/priceLists'
import { ApiError } from '@/api/http'
import {
  CATALOG_STATUS_LABELS,
  CATALOG_STATUS_OPTIONS,
  CATALOG_STATUS_TAG,
  PRICE_BASIS_LABELS,
} from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type {
  CatalogStatus,
  PriceBasis,
  PriceList,
  PriceListDetail,
  PriceTier,
  ProductSummary,
} from '@/types/product'
import { formatDateTime } from '@/utils/format'

import PriceListFormDialog from './PriceListFormDialog.vue'
import PriceTierFormDialog from './PriceTierFormDialog.vue'

const auth = useAuthStore()
const canUpdate = computed(() => auth.hasPermission('pricing:update'))

const filters = reactive({
  status: '' as CatalogStatus | '',
})

const rows = ref<PriceList[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const loading = ref(false)
const selectedId = ref('')
const detail = ref<PriceListDetail | null>(null)
const detailLoading = ref(false)
const products = ref<ProductSummary[]>([])

const listDialogVisible = ref(false)
const editingList = ref<PriceList | null>(null)
const tierDialogVisible = ref(false)
const editingTier = ref<PriceTier | null>(null)

const productMap = computed(() => new Map(products.value.map((item) => [item.id, item])))

function productLabel(productId: string): string {
  const product = productMap.value.get(productId)
  return product ? `${product.product_code} · ${product.product_name}` : productId
}

function quantityRange(tier: PriceTier): string {
  return tier.max_quantity === null
    ? `≥ ${tier.min_quantity}`
    : `${tier.min_quantity} ~ ${tier.max_quantity}`
}

function validityText(from: string | null, to: string | null): string {
  if (!from && !to) {
    return '长期'
  }
  if (!from) {
    return `至 ${to}`
  }
  return to ? `${from} 至 ${to}` : `${from} 起`
}

async function loadProducts(): Promise<void> {
  try {
    const envelope = await fetchProducts({ page_size: 100 })
    products.value = envelope.data
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载产品列表失败')
  }
}

async function loadDetail(priceListId: string): Promise<void> {
  detailLoading.value = true
  try {
    detail.value = await fetchPriceList(priceListId)
  } catch (error) {
    detail.value = null
    ElMessage.error(error instanceof ApiError ? error.message : '加载阶梯价失败')
  } finally {
    detailLoading.value = false
  }
}

function selectList(priceList: PriceList): void {
  selectedId.value = priceList.id
  void loadDetail(priceList.id)
}

async function loadLists(): Promise<void> {
  loading.value = true
  try {
    const envelope = await fetchPriceLists({
      page: page.value,
      page_size: pageSize.value,
      status: filters.status || undefined,
    })
    rows.value = envelope.data
    total.value = envelope.meta.total ?? envelope.data.length

    const target =
      rows.value.find((row) => row.id === selectedId.value) ?? rows.value[0] ?? null
    if (target) {
      if (target.id !== selectedId.value || !detail.value) {
        await selectList(target)
      } else {
        selectedId.value = target.id
      }
    } else {
      selectedId.value = ''
      detail.value = null
    }
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载价格表失败')
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  void loadLists()
}

function changePage(next: number): void {
  page.value = next
  void loadLists()
}

function changePageSize(size: number): void {
  pageSize.value = size
  page.value = 1
  void loadLists()
}

function openCreateList(): void {
  editingList.value = null
  listDialogVisible.value = true
}

function openEditList(priceList: PriceList): void {
  editingList.value = priceList
  listDialogVisible.value = true
}

async function handleListSaved(saved: PriceListDetail): Promise<void> {
  page.value = 1
  selectedId.value = saved.id
  detail.value = saved
  await loadLists()
}

async function openCreateTier(): Promise<void> {
  await loadProducts()
  editingTier.value = null
  tierDialogVisible.value = true
}

function openEditTier(tier: PriceTier): void {
  editingTier.value = tier
  tierDialogVisible.value = true
}

function handleTierSaved(): void {
  if (selectedId.value) {
    void loadDetail(selectedId.value)
  }
}

onMounted(() => {
  void loadLists()
  void loadProducts()
})
</script>

<template>
  <div class="pricing-panel">
    <el-card shadow="never" class="list-card">
      <div class="panel-toolbar">
        <span class="hint">点击价格表查看阶梯价；阶梯价按产品、数量区间与有效期命中报价。</span>
        <div class="toolbar-actions">
          <el-select
            v-model="filters.status"
            placeholder="全部状态"
            clearable
            style="width: 130px"
            @change="applyFilters"
          >
            <el-option
              v-for="option in CATALOG_STATUS_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-button :icon="Refresh" @click="loadLists">刷新</el-button>
          <el-button
            v-if="canUpdate"
            type="primary"
            :icon="Plus"
            @click="openCreateList"
          >
            新建价格表
          </el-button>
        </div>
      </div>

      <el-table
        v-loading="loading"
        :data="rows"
        row-key="id"
        highlight-current-row
        :current-row-key="selectedId"
        @row-click="selectList"
      >
        <el-table-column label="名称" min-width="220">
          <template #default="{ row }">
            <button class="name-link" type="button" @click.stop="selectList(row)">
              {{ row.name }}
            </button>
          </template>
        </el-table-column>
        <el-table-column prop="currency" label="币种" width="80" align="center" />
        <el-table-column label="版本" width="70" align="center">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="有效期" min-width="200">
          <template #default="{ row }">
            {{ row.valid_from }} 至 {{ row.valid_to || '长期' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="CATALOG_STATUS_TAG[row.status as CatalogStatus]" effect="plain">
              {{ CATALOG_STATUS_LABELS[row.status as CatalogStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column v-if="canUpdate" label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openEditList(row)">编辑</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无价格表，新建后可维护产品阶梯价" />
        </template>
      </el-table>

      <div class="pagination">
        <el-pagination
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="[10, 20, 50]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="changePage"
          @size-change="changePageSize"
        />
      </div>
    </el-card>

    <el-card v-if="detail" v-loading="detailLoading" shadow="never" class="detail-card">
      <div class="detail-head">
        <div>
          <div class="title-row">
            <h3>{{ detail.name }}</h3>
            <el-tag :type="CATALOG_STATUS_TAG[detail.status as CatalogStatus]" effect="plain">
              {{ CATALOG_STATUS_LABELS[detail.status as CatalogStatus] }}
            </el-tag>
          </div>
          <p class="subtitle">
            {{ detail.currency }} · v{{ detail.version }} ·
            {{ detail.valid_from }} 至 {{ detail.valid_to || '长期' }} · 更新于
            {{ formatDateTime(detail.updated_at) }}
          </p>
        </div>
        <div v-if="canUpdate" class="detail-actions">
          <el-button @click="openEditList(detail)">编辑信息</el-button>
          <el-button type="primary" :icon="Plus" @click="openCreateTier">新增阶梯价</el-button>
        </div>
      </div>

      <el-table :data="detail.tiers" row-key="id" class="tier-table">
        <el-table-column label="产品" min-width="240">
          <template #default="{ row }">{{ productLabel(row.product_id) }}</template>
        </el-table-column>
        <el-table-column label="数量区间" width="140">
          <template #default="{ row }">{{ quantityRange(row as PriceTier) }}</template>
        </el-table-column>
        <el-table-column label="单价" min-width="150">
          <template #default="{ row }">
            <strong class="price">{{ detail.currency }} {{ row.unit_price }}</strong>
            <span class="unit">/ {{ row.unit }}</span>
          </template>
        </el-table-column>
        <el-table-column label="计价方式" width="100" align="center">
          <template #default="{ row }">
            {{ PRICE_BASIS_LABELS[row.price_basis as PriceBasis] }}
          </template>
        </el-table-column>
        <el-table-column label="有效期" min-width="200">
          <template #default="{ row }">
            {{ validityText(row.valid_from, row.valid_to) }}
          </template>
        </el-table-column>
        <el-table-column v-if="canUpdate" label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEditTier(row as PriceTier)">
              编辑
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="该价格表还没有阶梯价" />
        </template>
      </el-table>
    </el-card>

    <el-card v-else shadow="never" class="detail-card">
      <el-empty description="选择上方价格表查看阶梯价" />
    </el-card>

    <PriceListFormDialog
      v-model="listDialogVisible"
      :price-list="editingList"
      @saved="handleListSaved"
    />
    <PriceTierFormDialog
      v-model="tierDialogVisible"
      :price-list-id="selectedId"
      :tier="editingTier"
      :products="products"
      @saved="handleTierSaved"
    />
  </div>
</template>

<style scoped>
.pricing-panel {
  display: grid;
  gap: 16px;
}

.list-card,
.detail-card {
  border-radius: 16px;
}

.panel-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hint {
  color: #8a97ad;
  font-size: 12px;
}

.name-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: #4f46e5;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.name-link:hover {
  text-decoration: underline;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-row h3 {
  margin: 0;
  color: #14213d;
  font-size: 18px;
}

.subtitle {
  margin: 6px 0 0;
  color: #7b879c;
  font-size: 12px;
}

.detail-actions {
  display: flex;
  gap: 10px;
}

.price {
  color: #14213d;
}

.unit {
  margin-left: 4px;
  color: #8a97ad;
  font-size: 12px;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
