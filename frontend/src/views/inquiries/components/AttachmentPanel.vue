<script setup lang="ts">
import { computed, ref } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'

import { ApiError } from '@/api/http'
import { uploadInquiryAttachment } from '@/api/inquiries'
import { SCAN_STATUS_LABELS, SCAN_STATUS_TAG } from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type { InquiryAttachment, ScanStatus } from '@/types/inquiry'
import { formatBytes, formatDateTime } from '@/utils/format'

const props = defineProps<{
  inquiryId: string
  attachments: InquiryAttachment[]
}>()

const emit = defineEmits<{
  uploaded: [attachment: InquiryAttachment]
}>()

const auth = useAuthStore()
const uploading = ref(false)
const canEdit = computed(() => auth.hasPermission('inquiry:update'))

async function doUpload(options: UploadRequestOptions): Promise<void> {
  uploading.value = true
  try {
    const attachment = await uploadInquiryAttachment(props.inquiryId, options.file)
    ElMessage.success('附件已上传')
    emit('uploaded', attachment)
    options.onSuccess(attachment as unknown as Record<string, unknown>)
  } catch (error) {
    const message =
      error instanceof ApiError
        ? error.code === 'ATTACHMENT_TOO_LARGE'
          ? '附件超过大小上限'
          : error.message
        : '附件上传失败，请稍后重试'
    ElMessage.error(message)
    options.onError(
      Object.assign(error instanceof Error ? error : new Error(message), {
        status: 0,
        method: 'POST',
        url: '',
      }) as unknown as Parameters<typeof options.onError>[0],
    )
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div class="attachment-panel">
    <el-upload
      v-if="canEdit"
      class="uploader"
      drag
      :show-file-list="false"
      :http-request="doUpload"
      :disabled="uploading"
    >
      <el-icon class="uploader-icon"><UploadFilled /></el-icon>
      <div class="uploader-text">
        <span>{{ uploading ? '上传中…' : '拖拽文件到此处，或点击选择文件' }}</span>
        <span class="uploader-hint">单个附件上限 20 MB，主要用于客户原始询盘文件。</span>
      </div>
    </el-upload>

    <el-table :data="attachments" row-key="id">
      <el-table-column prop="filename" label="文件名" min-width="240" />
      <el-table-column label="类型" width="160">
        <template #default="{ row }">{{ row.content_type || '—' }}</template>
      </el-table-column>
      <el-table-column label="大小" width="100" align="right">
        <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
      </el-table-column>
      <el-table-column label="扫描状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="SCAN_STATUS_TAG[row.scan_status as ScanStatus]" effect="plain" size="small">
            {{ SCAN_STATUS_LABELS[row.scan_status as ScanStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="上传时间" width="180">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无附件" />
      </template>
    </el-table>

    <p class="note">当前版本仅记录附件元数据，附件预览与下载将在后续里程碑提供。</p>
  </div>
</template>

<style scoped>
.attachment-panel {
  display: grid;
  gap: 14px;
}

.uploader :deep(.el-upload-dragger) {
  padding: 18px;
}

.uploader-icon {
  color: #94a3b8;
  font-size: 30px;
}

.uploader-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #475569;
  font-size: 13px;
}

.uploader-hint {
  color: #9aa6b8;
  font-size: 12px;
}

.note {
  margin: 0;
  color: #9aa6b8;
  font-size: 12px;
}
</style>
