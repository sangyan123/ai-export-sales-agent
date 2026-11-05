<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { fetchInquiries, type InquiryStatus, type InquirySummary } from '@/api/inquiries'
import { ApiError } from '@/api/http'
import {
  INQUIRY_SOURCE_LABELS,
  INQUIRY_STATUS_LABELS,
  INQUIRY_STATUS_TAG,
} from '@/constants/catalog'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ customerId: string }>()

const router = useRouter()
const rows = ref<InquirySummary[]>([])
const loading = ref(false)

function openDetail(inquiry: InquirySummary): void {
  void router.push({ name: 'inquiry-detail', params: { id: inquiry.id } })
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
      <el-table-column label="询盘主题" min-width="260">
        <template #default="{ row }">
          <button class="subject-link" type="button" @click="openDetail(row)">
            {{ row.subject }}
          </button>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="110" align="center">
        <template #default="{ row }">{{ INQUIRY_SOURCE_LABELS[row.source_type as InquirySummary['source_type']] }}</template>
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

.subject-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: #4f46e5;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.subject-link:hover {
  text-decoration: underline;
}
</style>
