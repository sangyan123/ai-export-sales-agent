<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Delete, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadRequestOptions } from 'element-plus'

import { deleteKnowledgeDocument, fetchKnowledgeDocuments, uploadKnowledgeDocument } from '@/api/products'
import { ApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import type { KnowledgeDocument, KnowledgeSource } from '@/types/product'
import { formatDateTime, formatBytes } from '@/utils/format'

const auth = useAuthStore()
const documents = ref<KnowledgeDocument[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const uploading = ref(false)
const filterSource = ref<string>('')
const searchQuery = ref('')

const canEdit = auth.hasPermission('product:import')

const SOURCE_OPTIONS: { value: KnowledgeSource; label: string }[] = [
  { value: 'CATALOG', label: '产品目录' },
  { value: 'PRICE_LIST', label: '价格表' },
  { value: 'CERTIFICATE', label: '证书' },
  { value: 'SPEC_SHEET', label: '规格书' },
  { value: 'OTHER', label: '其他' },
]

function sourceLabel(value: string) {
  return SOURCE_OPTIONS.find((option) => option.value === value)?.label ?? value
}

const UPLOAD_ACCEPT = '.pdf,.docx,.xlsx,.xls,.csv,.txt'

async function load() {
  loading.value = true
  try {
    const result = await fetchKnowledgeDocuments({
      page: page.value,
      page_size: pageSize,
      source: filterSource.value || undefined,
      q: searchQuery.value.trim() || undefined,
    })
    documents.value = result.data
    total.value = result.meta.total ?? 0
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载资料列表失败')
  } finally {
    loading.value = false
  }
}

async function customUpload(options: UploadRequestOptions) {
  uploading.value = true
  try {
    await uploadKnowledgeDocument(options.file as File)
    ElMessage.success('资料已上传')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '上传失败')
  } finally {
    uploading.value = false
  }
}

async function remove(doc: KnowledgeDocument) {
  try {
    await ElMessageBox.confirm(`确定删除「${doc.filename}」吗？删除后不可恢复。`, '删除资料', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await deleteKnowledgeDocument(doc.id)
    ElMessage.success('资料已删除')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '删除失败')
  }
}

function handlePageChange(newPage: number) {
  page.value = newPage
  load()
}

function handleFilterChange() {
  page.value = 1
  load()
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <div class="panel-toolbar">
      <div class="toolbar-filters">
        <el-select
          v-model="filterSource"
          placeholder="全部来源"
          clearable
          style="width: 140px"
          @change="handleFilterChange"
        >
          <el-option
            v-for="option in SOURCE_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-input
          v-model="searchQuery"
          placeholder="搜索文件名"
          clearable
          style="width: 200px"
          @change="handleFilterChange"
        />
      </div>
      <el-upload
        v-if="canEdit"
        :show-file-list="false"
        :accept="UPLOAD_ACCEPT"
        :http-request="customUpload"
      >
        <el-button type="primary" :icon="UploadFilled" :loading="uploading">上传资料</el-button>
      </el-upload>
    </div>

    <el-alert
      v-if="canEdit"
      type="info"
      :closable="false"
      show-icon
    >
      支持 PDF / DOCX / XLSX / CSV / TXT，单文件不超过 20 MB。上传后可在 AI 解析结果中引用出处。
    </el-alert>

    <el-table v-loading="loading" :data="documents" row-key="id">
      <el-table-column label="文件名" min-width="220">
        <template #default="{ row }">
          <span class="filename">{{ row.filename }}</span>
          <div v-if="row.description" class="description">{{ row.description }}</div>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="110" align="center">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ sourceLabel(row.source) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="解析状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag
            size="small"
            :type="row.parse_status === 'FAILED' ? 'danger' : row.parse_status === 'PARSED' ? 'success' : 'info'"
            effect="plain"
          >
            {{ row.parse_status === 'FAILED' ? '解析失败' : row.parse_status === 'PARSED' ? '已解析' : '已上传' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="100" align="right">
        <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
      </el-table-column>
      <el-table-column label="上传时间" width="180">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column v-if="canEdit" label="操作" width="90" align="center">
        <template #default="{ row }">
          <el-button link type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无知识资料，上传产品目录、价格表、证书等供 AI 解析引用" />
      </template>
    </el-table>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :total="total"
      :page-size="pageSize"
      layout="prev, pager, next"
      @current-change="handlePageChange"
    />
  </div>
</template>

<style scoped>
.panel {
  display: grid;
  gap: 12px;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.toolbar-filters {
  display: flex;
  gap: 8px;
}

.filename {
  font-weight: 600;
  color: #1b2a4a;
}

.description {
  color: #8a97ad;
  font-size: 12px;
  margin-top: 4px;
}
</style>
