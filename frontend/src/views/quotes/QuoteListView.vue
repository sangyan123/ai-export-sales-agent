<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { ApiError } from '@/api/http'
import { fetchInquiries } from '@/api/inquiries'
import { fetchQuotes, type QuoteDetail, type QuoteSummary } from '@/api/quotes'
import {
  QUOTE_STATUS_LABELS,
  QUOTE_STATUS_OPTIONS,
  QUOTE_STATUS_TAG,
} from '@/constants/catalog'
import type { QuoteStatus } from '@/types/quote'
import { formatAmount, formatDate, formatDateTime } from '@/utils/format'

import QuoteFormDialog from './components/QuoteFormDialog.vue'

const router = useRouter()

const filters = reactive({
  quote_no: '',
  status: '' as QuoteStatus | '',
})

const rows = ref<QuoteSummary[]>([])
const inquirySubjects = ref<Record<string, string>>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const createVisible = ref(false)

async function loadInquiries(): Promise<void> {
  try {
    const envelope = await fetchInquiries({ page: 1, page_size: 100 })
    inquirySubjects.value = Object.fromEntries(
      envelope.data.map((inquiry) => [inquiry.id, inquiry.subject]),
    )
  } catch {
    inquirySubjects.value = {}
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const envelope = await fetchQuotes({
      page: page.value,
      page_size: pageSize.value,
      status: filters.status || undefined,
      quote_no: filters.quote_no.trim() || undefined,
    })
    rows.value = envelope.data
    total.value = envelope.meta.total ?? envelope.data.length
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载报价列表失败')
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  void load()
}

function resetFilters(): void {
  filters.quote_no = ''
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

function openDetail(quote: QuoteSummary): void {
  void router.push({ name: 'quote-detail', params: { id: quote.id } })
}

function inquiryLabel(quote: QuoteSummary): string {
  if (!quote.inquiry_id) {
    return '—'
  }
  return inquirySubjects.value[quote.inquiry_id] || quote.inquiry_id.slice(0, 8)
}

function handleCreated(quote: QuoteDetail): void {
  createVisible.value = false
  void router.push({ name: 'quote-detail', params: { id: quote.id } })
}

onMounted(() => {
  void loadInquiries()
  void load()
})
</script>

<template>
  <section class="quote-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="page-head">
        <div>
          <h2>报价中心</h2>
          <p>创建报价草案、提交审批、跟踪版本与操作记录，并导出 PDF / XLSX 报价文件。</p>
        </div>
        <el-button
          v-permission="'quote:create'"
          type="primary"
          :icon="Plus"
          @click="createVisible = true"
        >
          新建报价
        </el-button>
      </div>

      <div class="filters">
        <el-input
          v-model="filters.quote_no"
          class="filter-search"
          placeholder="按报价编号精确查询"
          clearable
          :prefix-icon="Search"
          maxlength="40"
          @keyup.enter="applyFilters"
          @clear="applyFilters"
        />
        <el-select
          v-model="filters.status"
          placeholder="全部状态"
          clearable
          style="width: 160px"
          @change="applyFilters"
        >
          <el-option
            v-for="option in QUOTE_STATUS_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-button type="primary" :icon="Search" @click="applyFilters">查询</el-button>
        <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table v-loading="loading" :data="rows" row-key="id" @row-dblclick="openDetail">
        <el-table-column label="报价编号" min-width="210">
          <template #default="{ row }">
            <button class="quote-link" type="button" @click="openDetail(row)">
              {{ row.quote_no }}
            </button>
          </template>
        </el-table-column>
        <el-table-column label="版本" width="80" align="center">
          <template #default="{ row }">v{{ row.version_no }}</template>
        </el-table-column>
        <el-table-column label="关联询盘" min-width="220">
          <template #default="{ row }">{{ inquiryLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="QUOTE_STATUS_TAG[row.status as QuoteStatus]" effect="plain">
              {{ QUOTE_STATUS_LABELS[row.status as QuoteStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="币种" width="80" align="center" prop="currency" />
        <el-table-column label="报价总额" width="180" align="right">
          <template #default="{ row }">
            {{ formatAmount(row.grand_total_display, row.currency) }}
          </template>
        </el-table-column>
        <el-table-column label="有效期至" width="130">
          <template #default="{ row }">{{ formatDate(row.valid_until) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无报价，先新建一份报价草案" />
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

    <QuoteFormDialog v-model="createVisible" @created="handleCreated" />
  </section>
</template>

<style scoped>
.quote-page {
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

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 18px;
}

.filter-search {
  width: 300px;
}

.quote-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: #2563eb;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.quote-link:hover {
  text-decoration: underline;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
