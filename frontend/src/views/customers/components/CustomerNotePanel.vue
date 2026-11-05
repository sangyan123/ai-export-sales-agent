<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Delete, Edit } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createNote, deleteNote, fetchNotes, updateNote } from '@/api/customers'
import { ApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import type { CustomerNote } from '@/types/customer'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ customerId: string }>()

const auth = useAuthStore()
const notes = ref<CustomerNote[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const saving = ref(false)
const newContent = ref('')
const editingId = ref<string | null>(null)
const editingContent = ref('')

const canEdit = auth.hasPermission('customer:update')

async function load() {
  loading.value = true
  try {
    const result = await fetchNotes(props.customerId, {
      page: page.value,
      page_size: pageSize,
    })
    notes.value = result.data
    total.value = result.meta.total ?? 0
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载备注失败')
  } finally {
    loading.value = false
  }
}

async function submit() {
  const content = newContent.value.trim()
  if (!content) {
    ElMessage.warning('请输入备注内容')
    return
  }
  saving.value = true
  try {
    await createNote(props.customerId, { content })
    newContent.value = ''
    ElMessage.success('备注已添加')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '添加备注失败')
  } finally {
    saving.value = false
  }
}

function startEdit(note: CustomerNote) {
  editingId.value = note.id
  editingContent.value = note.content
}

function cancelEdit() {
  editingId.value = null
  editingContent.value = ''
}

async function saveEdit() {
  if (!editingId.value) return
  const content = editingContent.value.trim()
  if (!content) {
    ElMessage.warning('备注内容不能为空')
    return
  }
  saving.value = true
  try {
    await updateNote(props.customerId, editingId.value, { content })
    ElMessage.success('备注已更新')
    cancelEdit()
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '更新备注失败')
  } finally {
    saving.value = false
  }
}

async function remove(note: CustomerNote) {
  try {
    await ElMessageBox.confirm('确定删除这条备注吗？删除后不可恢复。', '删除备注', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await deleteNote(props.customerId, note.id)
    ElMessage.success('备注已删除')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '删除备注失败')
  }
}

function handlePageChange(newPage: number) {
  page.value = newPage
  load()
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <div v-if="canEdit" class="note-composer">
      <el-input
        v-model="newContent"
        type="textarea"
        :rows="3"
        maxlength="5000"
        show-word-limit
        placeholder="记录沟通要点、客户偏好、报价反馈等…"
      />
      <el-button type="primary" :loading="saving" :disabled="!newContent.trim()" @click="submit">
        添加备注
      </el-button>
    </div>

    <div v-loading="loading" class="note-list">
      <el-empty v-if="!loading && notes.length === 0" description="暂无备注，添加后形成客户沟通时间线" />
      <el-timeline v-else class="timeline">
        <el-timeline-item
          v-for="note in notes"
          :key="note.id"
          :timestamp="formatDateTime(note.created_at)"
          placement="top"
          type="primary"
        >
          <div class="note-card">
            <template v-if="editingId === note.id">
              <el-input
                v-model="editingContent"
                type="textarea"
                :rows="3"
                maxlength="5000"
                show-word-limit
              />
              <div class="note-actions">
                <el-button size="small" type="primary" :loading="saving" @click="saveEdit">保存</el-button>
                <el-button size="small" @click="cancelEdit">取消</el-button>
              </div>
            </template>
            <template v-else>
              <div class="note-content">{{ note.content }}</div>
              <div v-if="canEdit" class="note-actions">
                <el-button link type="primary" size="small" :icon="Edit" @click="startEdit(note)">编辑</el-button>
                <el-button link type="danger" size="small" :icon="Delete" @click="remove(note)">删除</el-button>
              </div>
            </template>
          </div>
        </el-timeline-item>
      </el-timeline>
    </div>

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
  gap: 16px;
}

.note-composer {
  display: grid;
  gap: 8px;
  justify-items: end;
}

.note-list {
  min-height: 120px;
}

.timeline {
  padding-left: 4px;
}

.note-card {
  background: #f8f9fb;
  border-radius: 6px;
  padding: 12px;
}

.note-content {
  white-space: pre-wrap;
  word-break: break-word;
  color: #1b2a4a;
  font-size: 14px;
  line-height: 1.6;
}

.note-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  margin-top: 8px;
}
</style>
