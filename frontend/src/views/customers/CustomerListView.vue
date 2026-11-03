<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchCustomers } from '@/api/customers'
import { ApiError } from '@/api/http'
import { CUSTOMER_STATUS_OPTIONS, CUSTOMER_STATUS_TAG, CUSTOMER_STATUS_LABELS } from '@/constants/catalog'
import type { Customer, CustomerStatus } from '@/types/customer'
import { formatDateTime } from '@/utils/format'

import CustomerFormDialog from './components/CustomerFormDialog.vue'

const router = useRouter()

const filters = reactive({
  q: '',
  status: '' as CustomerStatus | '',
  country_code: '',
})

const rows = ref<Customer[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const createVisible = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const envelope = await fetchCustomers({
      page: page.value,
      page_size: pageSize.value,
      q: filters.q.trim() || undefined,
      status: filters.status || undefined,
      country_code: filters.country_code.trim().toUpperCase() || undefined,
    })
    rows.value = envelope.data
    total.value = envelope.meta.total ?? envelope.data.length
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载客户列表失败')
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
  filters.country_code = ''
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

function openDetail(customer: Customer): void {
  void router.push({ name: 'customer-detail', params: { id: customer.id } })
}

function handleSaved(): void {
  page.value = 1
  void load()
}

onMounted(load)
</script>

<template>
  <section class="customer-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="page-head">
        <div>
          <h2>客户管理</h2>
          <p>维护客户档案、联系人与专属价格，查看关联询盘和跟进任务。</p>
        </div>
        <el-button
          v-permission="'customer:create'"
          type="primary"
          :icon="Plus"
          @click="createVisible = true"
        >
          新建客户
        </el-button>
      </div>

      <div class="filters">
        <el-input
          v-model="filters.q"
          class="filter-search"
          placeholder="搜索公司名称或网站"
          clearable
          :prefix-icon="Search"
          @keyup.enter="applyFilters"
          @clear="applyFilters"
        />
        <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 150px" @change="applyFilters">
          <el-option
            v-for="option in CUSTOMER_STATUS_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-input
          v-model="filters.country_code"
          placeholder="国家代码"
          maxlength="2"
          clearable
          style="width: 130px"
          @keyup.enter="applyFilters"
          @clear="applyFilters"
        />
        <el-button type="primary" :icon="Search" @click="applyFilters">查询</el-button>
        <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table v-loading="loading" :data="rows" row-key="id" @row-dblclick="openDetail">
        <el-table-column label="公司名称" min-width="240">
          <template #default="{ row }">
            <button class="company-link" type="button" @click="openDetail(row)">
              {{ row.company_name }}
            </button>
          </template>
        </el-table-column>
        <el-table-column prop="country_code" label="国家" width="90" align="center">
          <template #default="{ row }">{{ row.country_code || '—' }}</template>
        </el-table-column>
        <el-table-column label="网站" min-width="200">
          <template #default="{ row }">
            <a v-if="row.website" :href="row.website" target="_blank" rel="noreferrer" class="website-link">
              {{ row.website }}
            </a>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="140">
          <template #default="{ row }">{{ row.source || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="CUSTOMER_STATUS_TAG[row.status as CustomerStatus]" effect="plain">
              {{ CUSTOMER_STATUS_LABELS[row.status as CustomerStatus] }}
            </el-tag>
          </template>
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
          <el-empty description="暂无客户，先新建一个客户档案" />
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

    <CustomerFormDialog v-model="createVisible" @saved="handleSaved" />
  </section>
</template>

<style scoped>
.customer-page {
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
  width: 260px;
}

.company-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: #2563eb;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.company-link:hover {
  text-decoration: underline;
}

.website-link {
  color: #2563eb;
}

.website-link:hover {
  text-decoration: underline;
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
