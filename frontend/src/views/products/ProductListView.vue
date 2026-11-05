<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchProduct, fetchProducts } from '@/api/products'
import { ApiError } from '@/api/http'
import {
  CATALOG_STATUS_LABELS,
  CATALOG_STATUS_OPTIONS,
  CATALOG_STATUS_TAG,
  PRODUCT_CATEGORY_LABELS,
  PRODUCT_CATEGORY_OPTIONS,
  PRODUCT_CATEGORY_TAG,
} from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type {
  CatalogStatus,
  Product,
  ProductCategory,
  ProductSummary,
} from '@/types/product'
import { formatDateTime } from '@/utils/format'

import KnowledgeDocumentPanel from './components/KnowledgeDocumentPanel.vue'
import PriceListPanel from './components/PriceListPanel.vue'
import ProductFormDialog from './components/ProductFormDialog.vue'
import ProductImportPanel from './components/ProductImportPanel.vue'

const auth = useAuthStore()

const canUpdate = computed(() => auth.hasPermission('product:update'))
const canReadPricing = computed(() => auth.hasPermission('pricing:read'))

const activeTab = ref<'products' | 'imports' | 'pricing'>('products')

const filters = reactive({
  q: '',
  category: '' as ProductCategory | '',
  status: '' as CatalogStatus | '',
})

const rows = ref<ProductSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const editingProduct = ref<Product | null>(null)
const dialogVisible = ref(false)
const loadingEditId = ref('')

function specText(product: ProductSummary): string {
  const size =
    product.diameter && product.length
      ? `${product.diameter}×${product.length}`
      : product.diameter || product.length
  const parts = [product.material, product.grade, size, product.standard_code]
  return parts.filter(Boolean).join(' · ') || '—'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const envelope = await fetchProducts({
      page: page.value,
      page_size: pageSize.value,
      q: filters.q.trim() || undefined,
      category: filters.category || undefined,
      status: filters.status || undefined,
    })
    rows.value = envelope.data
    total.value = envelope.meta.total ?? envelope.data.length
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载产品列表失败')
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  void load()
}

function resetFilters(): void {
  filters.q = ''
  filters.category = ''
  filters.status = ''
  applyFilters()
}

function changePage(next: number): void {
  page.value = next
  void load()
}

function changePageSize(size: number): void {
  pageSize.value = size
  page.value = 1
  void load()
}

function openCreate(): void {
  editingProduct.value = null
  dialogVisible.value = true
}

async function openEdit(product: ProductSummary): Promise<void> {
  loadingEditId.value = product.id
  try {
    editingProduct.value = await fetchProduct(product.id)
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载产品资料失败')
  } finally {
    loadingEditId.value = ''
  }
}

function handleSaved(): void {
  void load()
}

function handleImported(): void {
  page.value = 1
  void load()
}

onMounted(load)
</script>

<template>
  <section class="product-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="page-head">
        <div>
          <h2>产品中心</h2>
          <p>维护紧固件产品规格与价格表，阶梯价按数量和有效期命中报价。</p>
        </div>
        <el-button
          v-if="activeTab === 'products'"
          v-permission="'product:create'"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >
          新建产品
        </el-button>
      </div>
    </el-card>

    <el-tabs v-model="activeTab" class="module-tabs">
      <el-tab-pane label="产品目录" name="products">
        <el-card shadow="never" class="table-card">
          <div class="filters">
            <el-input
              v-model="filters.q"
              class="filter-search"
              placeholder="搜索产品编码或名称"
              clearable
              :prefix-icon="Search"
              @keyup.enter="applyFilters"
              @clear="applyFilters"
            />
            <el-select
              v-model="filters.category"
              placeholder="全部品类"
              clearable
              style="width: 130px"
              @change="applyFilters"
            >
              <el-option
                v-for="option in PRODUCT_CATEGORY_OPTIONS"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
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
            <el-button type="primary" :icon="Search" @click="applyFilters">查询</el-button>
            <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
          </div>

          <el-table v-loading="loading" :data="rows" row-key="id">
            <el-table-column label="产品编码" width="180">
              <template #default="{ row }">
                <span class="code">{{ row.product_code }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="product_name" label="产品名称" min-width="200" />
            <el-table-column label="品类" width="90" align="center">
              <template #default="{ row }">
                <el-tag
                  :type="PRODUCT_CATEGORY_TAG[row.category as ProductCategory]"
                  effect="plain"
                >
                  {{ PRODUCT_CATEGORY_LABELS[row.category as ProductCategory] }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="规格" min-width="240">
              <template #default="{ row }">{{ specText(row) }}</template>
            </el-table-column>
            <el-table-column label="单位 / MOQ" width="130">
              <template #default="{ row }">
                {{ row.sales_unit }}
                <span class="muted">/ {{ row.moq ?? '—' }}</span>
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
            <el-table-column v-if="canUpdate" label="操作" width="90" fixed="right" align="center">
              <template #default="{ row }">
                <el-button
                  link
                  type="primary"
                  :loading="loadingEditId === row.id"
                  @click="openEdit(row)"
                >
                  编辑
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无产品，先新建一个产品档案" />
            </template>
          </el-table>

          <div class="pagination">
            <el-pagination
              :current-page="page"
              :page-size="pageSize"
              :page-sizes="[10, 20, 50, 100]"
              :total="total"
              layout="total, sizes, prev, pager, next"
              background
              @current-change="changePage"
              @size-change="changePageSize"
            />
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="Excel 导入" name="imports" lazy>
        <ProductImportPanel @imported="handleImported" />
      </el-tab-pane>

      <el-tab-pane v-if="canReadPricing" label="价格表" name="pricing" lazy>
        <PriceListPanel />
      </el-tab-pane>

      <el-tab-pane label="知识资料" name="knowledge" lazy>
        <KnowledgeDocumentPanel />
      </el-tab-pane>
    </el-tabs>

    <ProductFormDialog v-model="dialogVisible" :product="editingProduct" @saved="handleSaved" />
  </section>
</template>

<style scoped>
.product-page {
  display: grid;
  gap: 16px;
}

.toolbar-card,
.table-card {
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

.module-tabs {
  padding: 0 4px;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.filter-search {
  width: 260px;
}

.code {
  color: #1b2a4a;
  font-weight: 600;
}

.muted {
  color: #9aa6b8;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
