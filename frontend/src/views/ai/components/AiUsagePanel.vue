<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchUsageRecords, fetchUsageSummary } from '@/api/usage'
import { ApiError } from '@/api/http'
import type { AIUsageRecord, AIUsageSummary } from '@/types/ai'
import { formatDateTime } from '@/utils/format'

const summary = ref<AIUsageSummary | null>(null)
const records = ref<AIUsageRecord[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 10
const loading = ref(false)

const stats = computed(() => {
  if (!summary.value) return []
  return [
    { label: '调用次数', value: String(summary.value.call_count) },
    { label: 'Prompt Tokens', value: summary.value.prompt_tokens.toLocaleString() },
    { label: 'Completion Tokens', value: summary.value.completion_tokens.toLocaleString() },
    { label: '总 Tokens', value: summary.value.total_tokens.toLocaleString() },
    { label: '总耗时', value: `${(summary.value.total_duration_ms / 1000).toFixed(1)}s` },
  ]
})

function operationLabel(value: string) {
  return value === 'INQUIRY_PARSE' ? '询盘解析' : value === 'EMAIL_GENERATE' ? '邮件生成' : value
}

async function load() {
  loading.value = true
  try {
    const [summaryData, recordsData] = await Promise.all([
      fetchUsageSummary({ days: 30 }),
      fetchUsageRecords({ page: page.value, page_size: pageSize }),
    ])
    summary.value = summaryData
    records.value = recordsData.data
    total.value = recordsData.meta.total ?? 0
  } catch (error) {
    console.warn('usage load failed', error instanceof ApiError ? error.message : error)
  } finally {
    loading.value = false
  }
}

function handlePageChange(newPage: number) {
  page.value = newPage
  load()
}

onMounted(load)
</script>

<template>
  <el-card v-loading="loading" shadow="never" class="usage-card">
    <template #header>
      <div class="card-head">
        <span>模型用量（近 30 天）</span>
      </div>
    </template>

    <div v-if="summary" class="stats-row">
      <div v-for="stat in stats" :key="stat.label" class="stat-item">
        <div class="stat-value">{{ stat.value }}</div>
        <div class="stat-label">{{ stat.label }}</div>
      </div>
    </div>

    <el-table v-if="records.length > 0" :data="records" row-key="id" size="small" class="usage-table">
      <el-table-column label="操作" width="110">
        <template #default="{ row }">{{ operationLabel(row.operation_type) }}</template>
      </el-table-column>
      <el-table-column prop="model_id" label="模型" min-width="140" />
      <el-table-column label="Prompt" width="90" align="right">
        <template #default="{ row }">{{ row.prompt_tokens.toLocaleString() }}</template>
      </el-table-column>
      <el-table-column label="Completion" width="100" align="right">
        <template #default="{ row }">{{ row.completion_tokens.toLocaleString() }}</template>
      </el-table-column>
      <el-table-column label="总 Tokens" width="100" align="right">
        <template #default="{ row }">{{ row.total_tokens.toLocaleString() }}</template>
      </el-table-column>
      <el-table-column label="耗时" width="90" align="right">
        <template #default="{ row }">{{ (row.duration_ms / 1000).toFixed(1) }}s</template>
      </el-table-column>
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="暂无 AI 调用记录" :image-size="48" />

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :total="total"
      :page-size="pageSize"
      layout="prev, pager, next"
      class="usage-pagination"
      @current-change="handlePageChange"
    />
  </el-card>
</template>

<style scoped>
.usage-card {
  margin-top: 0;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
}

.stats-row {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.stat-item {
  min-width: 100px;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #1b2a4a;
}

.stat-label {
  font-size: 12px;
  color: #8a97ad;
  margin-top: 2px;
}

.usage-pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
