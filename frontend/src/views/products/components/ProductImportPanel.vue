<script setup lang="ts">
import { computed, ref } from 'vue'
import { Download, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'

import { ApiError } from '@/api/http'
import { downloadProductImportTemplate, importProducts } from '@/api/products'
import {
  PRODUCT_IMPORT_ERROR_MESSAGES,
  PRODUCT_IMPORT_FIELD_LABELS,
  PRODUCT_IMPORT_ROW_ERROR_LABELS,
  PRODUCT_IMPORT_STATUS_LABELS,
  PRODUCT_IMPORT_STATUS_TAG,
} from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type { ProductImportJob, ProductImportRowError } from '@/types/product'
import { formatDateTime } from '@/utils/format'

const emit = defineEmits<{
  imported: []
}>()

const auth = useAuthStore()
const canImport = computed(() => auth.hasPermission('product:import'))

const MAX_FILE_BYTES = 20 * 1024 * 1024

const downloading = ref(false)
const importing = ref(false)
const job = ref<ProductImportJob | null>(null)

function importErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return PRODUCT_IMPORT_ERROR_MESSAGES[error.code] ?? error.message
  }
  return fallback
}

function fileError(file: File): string | null {
  const name = file.name.toLowerCase()
  if (!name.endsWith('.xlsx') && !name.endsWith('.xlsm')) {
    return '仅支持 .xlsx 或 .xlsm 文件'
  }
  if (!file.size) {
    return '文件内容为空，请重新选择'
  }
  if (file.size > MAX_FILE_BYTES) {
    return '文件超过 20 MB 上限'
  }
  return null
}

async function downloadTemplate(): Promise<void> {
  downloading.value = true
  try {
    const template = await downloadProductImportTemplate()
    const url = URL.createObjectURL(template.blob)
    const link = window.document.createElement('a')
    link.href = url
    link.download = template.filename
    window.document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('导入模板已下载')
  } catch (error) {
    ElMessage.error(importErrorMessage(error, '下载模板失败，请稍后重试'))
  } finally {
    downloading.value = false
  }
}

function rejectUpload(options: UploadRequestOptions, message: string): void {
  ElMessage.error(message)
  options.onError(
    Object.assign(new Error(message), {
      status: 0,
      method: 'POST',
      url: '',
    }) as unknown as Parameters<typeof options.onError>[0],
  )
}

async function doUpload(options: UploadRequestOptions): Promise<void> {
  const invalid = fileError(options.file)
  if (invalid) {
    rejectUpload(options, invalid)
    return
  }

  importing.value = true
  job.value = null
  try {
    const result = await importProducts(options.file)
    job.value = result
    if (result.status === 'SUCCEEDED') {
      ElMessage.success(`成功导入 ${result.imported} 个产品`)
      emit('imported')
    } else {
      ElMessage.warning(`导入未完成：${result.failed} 行校验未通过，产品未写入`)
    }
    options.onSuccess(result as unknown as Record<string, unknown>)
  } catch (error) {
    ElMessage.error(importErrorMessage(error, '导入失败，请稍后重试'))
    options.onError(
      Object.assign(error instanceof Error ? error : new Error('导入失败'), {
        status: 0,
        method: 'POST',
        url: '',
      }) as unknown as Parameters<typeof options.onError>[0],
    )
  } finally {
    importing.value = false
  }
}

function fieldLabel(error: ProductImportRowError): string {
  if (!error.field) {
    return '整行'
  }
  return PRODUCT_IMPORT_FIELD_LABELS[error.field] ?? error.field
}

function errorLabel(error: ProductImportRowError): string {
  return PRODUCT_IMPORT_ROW_ERROR_LABELS[error.code] ?? error.code
}
</script>

<template>
  <div class="import-panel">
    <el-card shadow="never" class="intro-card">
      <div class="intro-head">
        <div>
          <h3>批量导入产品</h3>
          <p>
            使用标准模板填写产品档案，系统会先校验全部行，通过后一次性写入；任一行有误则整批不导入。
          </p>
        </div>
        <el-button :icon="Download" :loading="downloading" @click="downloadTemplate">
          下载模板
        </el-button>
      </div>
      <ul class="hints">
        <li>支持 .xlsx / .xlsm，单个文件不超过 20 MB，单次最多 5000 行。</li>
        <li>必填列为产品编码、产品名称、产品类别、计价单位，产品编码不可重复。</li>
        <li>产品类别可填 BOLT / NUT / SCREW / WASHER / OTHER，也可使用中文名称。</li>
        <li>MOQ 为非负数字，最多 4 位小数；留空表示未设置。</li>
      </ul>
    </el-card>

    <el-card shadow="never" class="upload-card">
      <el-upload
        v-if="canImport"
        class="uploader"
        drag
        accept=".xlsx,.xlsm"
        :show-file-list="false"
        :http-request="doUpload"
        :disabled="importing"
      >
        <el-icon class="uploader-icon"><UploadFilled /></el-icon>
        <div class="uploader-text">
          <span>{{ importing ? '正在校验并导入…' : '拖拽 Excel 文件到此处，或点击选择文件' }}</span>
          <span class="uploader-hint">上传后会立即校验模板结构与每一行数据。</span>
        </div>
      </el-upload>
      <el-alert
        v-else
        type="info"
        :closable="false"
        show-icon
        title="当前账号可下载模板，但没有产品导入权限"
        description="如需批量导入，请联系拥有 product:import 权限的管理员账号操作。"
      />
    </el-card>

    <el-card v-if="job" shadow="never" class="result-card">
      <div class="result-head">
        <div class="title-row">
          <h3>导入结果</h3>
          <el-tag :type="PRODUCT_IMPORT_STATUS_TAG[job.status]" effect="plain">
            {{ PRODUCT_IMPORT_STATUS_LABELS[job.status] }}
          </el-tag>
        </div>
        <el-button link @click="job = null">清除结果</el-button>
      </div>

      <el-descriptions :column="3" size="small" border>
        <el-descriptions-item label="文件名">{{ job.filename || '—' }}</el-descriptions-item>
        <el-descriptions-item label="总行数">{{ job.total_rows }}</el-descriptions-item>
        <el-descriptions-item label="成功导入">{{ job.imported }}</el-descriptions-item>
        <el-descriptions-item label="失败行数">{{ job.failed }}</el-descriptions-item>
        <el-descriptions-item label="完成时间">
          {{ formatDateTime(job.finished_at) || '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="任务编号">
          <span class="job-id">{{ job.id }}</span>
        </el-descriptions-item>
      </el-descriptions>

      <template v-if="job.errors.length">
        <div class="errors-head">
          <span>错误明细（第 2 行起为数据行）</span>
          <span v-if="job.errors_truncated" class="truncated">
            错误过多，仅展示前 {{ job.errors.length }} 条
          </span>
        </div>
        <el-table :data="job.errors" row-key="row" size="small">
          <el-table-column prop="row" label="行号" width="70" align="center" />
          <el-table-column label="字段" width="120">
            <template #default="{ row }">{{ fieldLabel(row) }}</template>
          </el-table-column>
          <el-table-column label="错误原因" width="170">
            <template #default="{ row }">
              <el-tag type="danger" effect="plain" size="small">{{ errorLabel(row) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="260" />
        </el-table>
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.import-panel {
  display: grid;
  gap: 16px;
}

.intro-card,
.upload-card,
.result-card {
  border-radius: 16px;
}

.intro-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.intro-head h3 {
  margin: 0;
  color: #14213d;
  font-size: 18px;
}

.intro-head p {
  margin: 6px 0 0;
  color: #7b879c;
  font-size: 13px;
}

.hints {
  display: grid;
  gap: 4px;
  margin: 14px 0 0;
  padding-left: 18px;
  color: #8a97ad;
  font-size: 12px;
}

.uploader :deep(.el-upload-dragger) {
  padding: 26px;
}

.uploader-icon {
  color: #94a3b8;
  font-size: 32px;
}

.uploader-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: #475569;
  font-size: 13px;
}

.uploader-hint {
  color: #8a97ad;
  font-size: 12px;
}

.result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-row h3 {
  margin: 0;
  color: #14213d;
  font-size: 18px;
}

.job-id {
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
}

.errors-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 18px 0 10px;
  color: #14213d;
  font-size: 14px;
  font-weight: 600;
}

.truncated {
  color: #b45309;
  font-size: 12px;
  font-weight: 400;
}
</style>
