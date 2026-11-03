<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchCustomers } from '@/api/customers'
import { ApiError } from '@/api/http'
import { fetchInquiries } from '@/api/inquiries'
import {
  INQUIRY_SOURCE_LABELS,
  INQUIRY_STATUS_LABELS,
  INQUIRY_STATUS_OPTIONS,
  INQUIRY_STATUS_TAG,
} from '@/constants/catalog'
import type { InquiryStatus, InquirySummary } from '@/types/inquiry'
import { formatDateTime } from '@/utils/format'

import InquiryFormDialog from './components/InquiryFormDialog.vue'

const router = useRouter()

const filters = reactive({
  q: '',
  status: '' as InquiryStatus | '',
})

const rows = ref<InquirySummary[]>([])
const customerNames = ref<Record<string, string>>({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const createVisible = ref(false)

async function loadCustomers(): Promise<void> {
  try {
    const envelope = await fetchCustomers({ page: 1, page_size: 100 })
    customerNames.value = Object.fromEntries(
      envelope.data.map((customer) => [customer.id, customer.company_name]),
    )
  } catch {
    customerNames.value = {}
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const envelope = await fetchInquiries({
      page: page.value,
      page_size: pageSize.value,
      q: filters.q.trim() || undefined,
      status: filters.status || undefined,
    })
    rows.value = envelope.data
    total.value = envelope.meta.total ?? envelope.data.length
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载询盘列表失败')
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

function openDetail(inquiry: InquirySummary): void {
  void router.push({ name: 'inquiry-detail', params: { id: inquiry.id } })
}

function handleSaved(): void {
  page.value = 1
  void load()
}

onMounted(() => {
  void loadCustomers()
  void load()
})
</script>

<template>
  <section class="inquiry-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="page-head">
        <div>
          <h2>询盘管理</h2>
          <p>集中处理原始询盘、AI 解析结果、人工确认字段与产品匹配候选。</p>
        </div>
        <el-button
          v-permission="'inquiry:create'"
          type="primary"
          :icon="Plus"
          @click="createVisible = true"
        >
          新建询盘
        </el-button>
      </div>

      <div class="filters">
        <el-input
          v-model="filters.q"
          class="filter-search"
          placeholder="搜索询盘主题或原始内容"
          clearable
          :prefix-icon="Search"
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
            v-for="option in INQUIRY_STATUS_OPTIONS"
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
        <el-table-column label="询盘主题" min-width="280">
          <template #default="{ row }">
            <button class="subject-link" type="button" @click="openDetail(row)">
              {{ row.subject }}
            </button>
          </template>
        </el-table-column>
        <el-table-column label="客户" min-width="180">
          <template #default="{ row }">
            {{ customerNames[row.customer_id] || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100" align="center">
          <template #default="{ row }">
            {{ INQUIRY_SOURCE_LABELS[row.source_type as keyof typeof INQUIRY_SOURCE_LABELS] }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="INQUIRY_STATUS_TAG[row.status as InquiryStatus]" effect="plain">
              {{ INQUIRY_STATUS_LABELS[row.status as InquiryStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="接收时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.received_at) }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无询盘，先新建一条询盘记录" />
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

    <InquiryFormDialog v-model="createVisible" @saved="handleSaved" />
  </section>
</template>

<style scoped>
.inquiry-page {
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

.subject-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: #2563eb;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.subject-link:hover {
  text-decoration: underline;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
