<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchAuditLogs } from '@/api/audit'
import { ApiError } from '@/api/http'
import type { TagType } from '@/constants/catalog'
import {
  AUDIT_ACTION_LABELS,
  AUDIT_RESOURCE_TYPE_LABELS,
  AUDIT_RESOURCE_TYPE_OPTIONS,
  AUDIT_RESOURCE_TYPE_TAG,
} from '@/constants/audit'
import type { AuditLogEntry } from '@/types/audit'
import { formatDateTime } from '@/utils/format'

const filters = reactive({
  action: '',
  resource_type: '',
})
const dateRange = ref<string[]>([])

const rows = ref<AuditLogEntry[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const detailVisible = ref(false)
const selected = ref<AuditLogEntry | null>(null)

const prettyMetadata = computed(() =>
  selected.value ? JSON.stringify(selected.value.metadata, null, 2) : '',
)

async function load(): Promise<void> {
  loading.value = true
  try {
    const envelope = await fetchAuditLogs({
      page: page.value,
      page_size: pageSize.value,
      action: filters.action.trim() || undefined,
      resource_type: filters.resource_type || undefined,
      created_from: dateRange.value[0] || undefined,
      created_to: dateRange.value[1] || undefined,
    })
    rows.value = envelope.data
    total.value = envelope.meta.total ?? envelope.data.length
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载审计日志失败')
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  void load()
}

function resetFilters(): void {
  filters.action = ''
  filters.resource_type = ''
  dateRange.value = []
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

function actionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action] ?? action
}

function resourceLabel(type: string): string {
  return AUDIT_RESOURCE_TYPE_LABELS[type] ?? type
}

function resourceTag(type: string): TagType {
  return AUDIT_RESOURCE_TYPE_TAG[type] ?? 'info'
}

function shortId(value: string | null): string {
  return value ? value.slice(0, 8) : '—'
}

function metadataSummary(entry: AuditLogEntry): string {
  const entries = Object.keys(entry.metadata ?? {})
  if (entries.length === 0) {
    return '—'
  }
  const text = JSON.stringify(entry.metadata)
  return text.length > 60 ? `${text.slice(0, 60)}…` : text
}

function openDetail(entry: AuditLogEntry): void {
  selected.value = entry
  detailVisible.value = true
}

onMounted(load)
</script>

<template>
  <section class="audit-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="page-head">
        <div>
          <h2>审计日志</h2>
          <p>记录企业内的关键写操作，仅展示当前企业的日志，按时间倒序排列。</p>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <div class="filters">
        <el-input
          v-model="filters.action"
          class="filter-action"
          placeholder="操作代码，如 quote.approve"
          clearable
          @keyup.enter="applyFilters"
          @clear="applyFilters"
        />
        <el-select
          v-model="filters.resource_type"
          placeholder="全部资源类型"
          clearable
          style="width: 160px"
          @change="applyFilters"
        >
          <el-option
            v-for="option in AUDIT_RESOURCE_TYPE_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-date-picker
          v-model="dateRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          value-format="YYYY-MM-DDTHH:mm:ssZ"
          style="width: 380px"
        />
        <el-button type="primary" :icon="Search" @click="applyFilters">查询</el-button>
        <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
      </div>

      <el-table v-loading="loading" :data="rows" row-key="id">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="200">
          <template #default="{ row }">
            <div class="action-cell">
              <span class="action-label">{{ actionLabel(row.action) }}</span>
              <span class="action-code">{{ row.action }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="资源类型" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="resourceTag(row.resource_type)" effect="plain">
              {{ resourceLabel(row.resource_type) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="资源 ID" width="120">
          <template #default="{ row }">
            <el-tooltip :content="row.resource_id || '—'" placement="top">
              <span class="mono">{{ shortId(row.resource_id) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="操作人" width="120">
          <template #default="{ row }">
            <el-tooltip :content="row.actor_id || '系统'" placement="top">
              <span class="mono">{{ shortId(row.actor_id) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="元数据" min-width="220">
          <template #default="{ row }">
            <span class="metadata">{{ metadataSummary(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无审计日志" />
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

    <el-dialog v-model="detailVisible" title="审计日志详情" width="640px">
      <template v-if="selected">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="操作">
            {{ actionLabel(selected.action) }}
            <span class="action-code">{{ selected.action }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="资源类型">
            {{ resourceLabel(selected.resource_type) }}（{{ selected.resource_type }}）
          </el-descriptions-item>
          <el-descriptions-item label="资源 ID">
            <span class="mono">{{ selected.resource_id || '—' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="操作人">
            <span class="mono">{{ selected.actor_id || '系统' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="请求 ID">
            <span class="mono">{{ selected.request_id || '—' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="IP 摘要">
            <span class="mono">{{ selected.ip_hash || '—' }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="发生时间">
            {{ formatDateTime(selected.created_at) }}
          </el-descriptions-item>
        </el-descriptions>
        <div class="metadata-block">
          <h4>元数据</h4>
          <pre>{{ prettyMetadata }}</pre>
        </div>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.audit-page {
  display: grid;
  gap: 16px;
}

.toolbar-card,
.table-card {
  border-radius: 16px;
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
  margin-bottom: 16px;
}

.filter-action {
  width: 240px;
}

.action-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.action-label {
  color: #1b2a4a;
  font-weight: 600;
}

.action-code {
  margin-left: 6px;
  color: #9aa6b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}

.metadata {
  color: #5b6884;
  font-size: 12px;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.metadata-block {
  margin-top: 16px;
}

.metadata-block h4 {
  margin: 0 0 8px;
  color: #14213d;
  font-size: 14px;
}

.metadata-block pre {
  max-height: 260px;
  margin: 0;
  padding: 12px 14px;
  overflow: auto;
  border-radius: 10px;
  background: #f6f8fb;
  color: #33415c;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
