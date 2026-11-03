<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { fetchFollowups, type FollowupStatus, type FollowupTaskSummary } from '@/api/followups'
import { ApiError } from '@/api/http'
import { FOLLOWUP_STATUS_LABELS, FOLLOWUP_STATUS_TAG } from '@/constants/catalog'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ customerId: string }>()

const rows = ref<FollowupTaskSummary[]>([])
const loading = ref(false)

const SOURCE_LABELS: Record<FollowupTaskSummary['source'], string> = {
  MANUAL: '手动创建',
  RULE: '规则生成',
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const envelope = await fetchFollowups({ customer_id: props.customerId, page_size: 50 })
    rows.value = envelope.data
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载跟进任务失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <el-table v-loading="loading" :data="rows" row-key="id">
      <el-table-column prop="title" label="任务" min-width="260" />
      <el-table-column label="到期时间" width="180">
        <template #default="{ row }">{{ formatDateTime(row.due_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="FOLLOWUP_STATUS_TAG[row.status as FollowupStatus]" effect="plain">
            {{ FOLLOWUP_STATUS_LABELS[row.status as FollowupStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="110" align="center">
        <template #default="{ row }">{{ SOURCE_LABELS[row.source as FollowupTaskSummary['source']] }}</template>
      </el-table-column>
      <el-table-column label="完成时间" width="180">
        <template #default="{ row }">{{ formatDateTime(row.completed_at) }}</template>
      </el-table-column>
      <template #empty>
        <el-empty description="该客户还没有跟进任务" />
      </template>
    </el-table>
  </div>
</template>

<style scoped>
.panel {
  display: grid;
  gap: 12px;
}
</style>
