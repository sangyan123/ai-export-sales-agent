<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { fetchInquiries, type InquiryStatus, type InquirySummary } from '@/api/inquiries'
import { ApiError } from '@/api/http'
import { INQUIRY_STATUS_LABELS, INQUIRY_STATUS_TAG } from '@/constants/catalog'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ customerId: string }>()

const rows = ref<InquirySummary[]>([])
const loading = ref(false)

const SOURCE_LABELS: Record<InquirySummary['source_type'], string> = {
  MANUAL: '手工录入',
  EMAIL: '邮件',
  UPLOAD: '上传',
  OTHER: '其他',
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const envelope = await fetchInquiries({ customer_id: props.customerId, page_size: 50 })
    rows.value = envelope.data
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载关联询盘失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <el-table v-loading="loading" :data="rows" row-key="id">
      <el-table-column prop="subject" label="询盘主题" min-width="260" />
      <el-table-column label="来源" width="110" align="center">
        <template #default="{ row }">{{ SOURCE_LABELS[row.source_type as InquirySummary['source_type']] }}</template>
      </el-table-column>
      <el-table-column label="状态" width="120" align="center">
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
      <template #empty>
        <el-empty description="该客户还没有询盘记录" />
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
