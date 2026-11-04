<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { fetchCustomers } from '@/api/customers'
import { fetchFollowups, followupErrorMessage, updateFollowup } from '@/api/followups'
import { fetchInquiries } from '@/api/inquiries'
import {
  FOLLOWUP_SOURCE_LABELS,
  FOLLOWUP_STATUS_LABELS,
  FOLLOWUP_STATUS_OPTIONS,
  FOLLOWUP_STATUS_TAG,
} from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type { Customer } from '@/types/customer'
import type { FollowupStatus, FollowupTask } from '@/types/followup'
import type { InquirySummary } from '@/types/inquiry'
import { formatDateTime } from '@/utils/format'

import FollowupFormDialog from './components/FollowupFormDialog.vue'

const auth = useAuthStore()

const filters = reactive({
  status: '' as FollowupStatus | '',
  customer_id: '',
  onlyOverdue: false,
  onlyMine: false,
})

const rows = ref<FollowupTask[]>([])
const customers = ref<Customer[]>([])
const inquiries = ref<InquirySummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const customersLoading = ref(false)
const dialogVisible = ref(false)
const editingTask = ref<FollowupTask | null>(null)

const canUpdate = computed(() => auth.hasPermission('followup:update'))

const customerNames = computed(() =>
  Object.fromEntries(customers.value.map((customer) => [customer.id, customer.company_name])),
)
const inquirySubjects = computed(() =>
  Object.fromEntries(inquiries.value.map((inquiry) => [inquiry.id, inquiry.subject])),
)

async function loadCustomers(): Promise<void> {
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
  try {
    const envelope = await fetchInquiries({ page: 1, page_size: 100 })
    inquiries.value = envelope.data
  } catch {
    inquiries.value = []
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const envelope = await fetchFollowups({
      page: page.value,
      page_size: pageSize.value,
      status: filters.status || undefined,
      customer_id: filters.customer_id || undefined,
      overdue: filters.onlyOverdue || undefined,
      assigned_to: filters.onlyMine ? auth.user?.id : undefined,
    })
    rows.value = envelope.data
    total.value = envelope.meta.total ?? envelope.data.length
  } catch (error) {
    ElMessage.error(followupErrorMessage(error, '加载跟进任务失败'))
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  void load()
}

function resetFilters(): void {
  filters.status = ''
  filters.customer_id = ''
  filters.onlyOverdue = false
  filters.onlyMine = false
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

function isOverdue(task: FollowupTask): boolean {
  return task.status === 'PENDING' && new Date(task.due_at).getTime() < Date.now()
}

function customerLabel(task: FollowupTask): string {
  return customerNames.value[task.customer_id] || task.customer_id.slice(0, 8)
}

function inquiryLabel(task: FollowupTask): string {
  if (!task.inquiry_id) {
    return '—'
  }
  return inquirySubjects.value[task.inquiry_id] || task.inquiry_id.slice(0, 8)
}

function assigneeLabel(task: FollowupTask): string {
  if (!task.assigned_to) {
    return '—'
  }
  return task.assigned_to === auth.user?.id ? '我' : task.assigned_to.slice(0, 8)
}

function openCreate(): void {
  editingTask.value = null
  dialogVisible.value = true
}

function openEdit(task: FollowupTask): void {
  editingTask.value = task
  dialogVisible.value = true
}

function handleSaved(): void {
  dialogVisible.value = false
  void load()
}

async function runStatus(
  task: FollowupTask,
  status: FollowupStatus,
  successMessage: string,
  confirmMessage?: string,
): Promise<void> {
  if (confirmMessage) {
    try {
      await ElMessageBox.confirm(confirmMessage, '提示', {
        type: 'warning',
        confirmButtonText: '确认',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
  }
  try {
    await updateFollowup(task.id, { status })
    ElMessage.success(successMessage)
    await load()
  } catch (error) {
    ElMessage.error(followupErrorMessage(error, '更新跟进状态失败'))
  }
}

function complete(task: FollowupTask): void {
  void runStatus(task, 'DONE', '跟进任务已完成', '确认将该跟进任务标记为已完成？')
}

function cancelTask(task: FollowupTask): void {
  void runStatus(task, 'CANCELLED', '跟进任务已取消', '确认取消该跟进任务？')
}

function reopen(task: FollowupTask): void {
  void runStatus(task, 'PENDING', '跟进任务已重新打开')
}

onMounted(() => {
  void loadCustomers()
  void loadInquiries()
  void load()
})
</script>

<template>
  <section class="followup-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="page-head">
        <div>
          <h2>跟进管理</h2>
          <p>按到期时间管理客户跟进任务，记录完成与重新安排，避免询盘和报价被遗忘。</p>
        </div>
        <el-button
          v-permission="'followup:create'"
          type="primary"
          :icon="Plus"
          @click="openCreate"
        >
          新建跟进
        </el-button>
      </div>

      <div class="filters">
        <el-select
          v-model="filters.status"
          placeholder="全部状态"
          clearable
          style="width: 150px"
          @change="applyFilters"
        >
          <el-option
            v-for="option in FOLLOWUP_STATUS_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-select
          v-model="filters.customer_id"
          placeholder="全部客户"
          filterable
          clearable
          :loading="customersLoading"
          style="width: 260px"
          @change="applyFilters"
        >
          <el-option
            v-for="customer in customers"
            :key="customer.id"
            :label="customer.company_name"
            :value="customer.id"
          />
        </el-select>
        <el-checkbox v-model="filters.onlyOverdue" @change="applyFilters">仅看逾期</el-checkbox>
        <el-checkbox v-model="filters.onlyMine" @change="applyFilters">只看我的</el-checkbox>
        <el-button type="primary" :icon="Search" @click="applyFilters">查询</el-button>
        <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table v-loading="loading" :data="rows" row-key="id">
        <el-table-column label="跟进内容" min-width="260" prop="title" />
        <el-table-column label="客户" min-width="190">
          <template #default="{ row }">{{ customerLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="关联询盘" min-width="190">
          <template #default="{ row }">{{ inquiryLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="到期时间" width="200">
          <template #default="{ row }">
            <span :class="{ overdue: isOverdue(row) }">{{ formatDateTime(row.due_at) }}</span>
            <el-tag v-if="isOverdue(row)" type="danger" size="small" effect="plain" class="overdue-tag">
              逾期
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="负责人" width="100" align="center">
          <template #default="{ row }">{{ assigneeLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="FOLLOWUP_STATUS_TAG[row.status as FollowupStatus]" effect="plain">
              {{ FOLLOWUP_STATUS_LABELS[row.status as FollowupStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="110" align="center">
          <template #default="{ row }">{{ FOLLOWUP_SOURCE_LABELS[row.source as FollowupTask['source']] }}</template>
        </el-table-column>
        <el-table-column label="完成时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.completed_at) }}</template>
        </el-table-column>
        <el-table-column v-if="canUpdate" label="操作" width="210" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'PENDING'"
              link
              type="success"
              @click="complete(row)"
            >
              完成
            </el-button>
            <el-button
              v-if="row.status === 'PENDING'"
              link
              type="warning"
              @click="cancelTask(row)"
            >
              取消
            </el-button>
            <el-button v-else link type="primary" @click="reopen(row)">重新打开</el-button>
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无跟进任务，先新建一条客户跟进" />
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

    <FollowupFormDialog
      v-model="dialogVisible"
      :task="editingTask"
      @saved="handleSaved"
    />
  </section>
</template>

<style scoped>
.followup-page {
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
  align-items: center;
  gap: 10px;
  margin-top: 18px;
}

.overdue {
  color: #dc2626;
  font-weight: 600;
}

.overdue-tag {
  margin-left: 6px;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
