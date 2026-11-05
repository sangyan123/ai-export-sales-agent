<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Edit, MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchCustomer } from '@/api/customers'
import { ApiError } from '@/api/http'
import { fetchInquiry, requestInquiryAnalysis, updateInquiry } from '@/api/inquiries'
import {
  INQUIRY_SOURCE_LABELS,
  INQUIRY_STATUS_LABELS,
  INQUIRY_STATUS_TAG,
  INQUIRY_STATUS_TRANSITIONS,
} from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type { InquiryDetail, InquirySourceType, InquiryStatus } from '@/types/inquiry'
import { formatDateTime } from '@/utils/format'

import AttachmentPanel from './components/AttachmentPanel.vue'
import InquiryFormDialog from './components/InquiryFormDialog.vue'
import MatchPanel from './components/MatchPanel.vue'
import RequirementPanel from './components/RequirementPanel.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const ANALYZABLE_STATUSES: InquiryStatus[] = ['RECEIVED', 'NEEDS_INFO']

const inquiry = ref<InquiryDetail | null>(null)
const customerName = ref('')
const loading = ref(false)
const errorMessage = ref('')
const activeTab = ref('body')

const editVisible = ref(false)
const statusVisible = ref(false)
const targetStatus = ref<InquiryStatus>('RECEIVED')
const statusSaving = ref(false)
const analysisLoading = ref(false)
const analysisRequested = ref(false)
const refreshKey = ref(0)

let pollTimer: number | null = null

const inquiryId = computed(() => String(route.params.id ?? ''))
const canEdit = computed(() => auth.hasPermission('inquiry:update'))
const canRunAi = computed(() => auth.hasPermission('ai:run'))
const canReadCustomers = computed(() => auth.hasPermission('customer:read'))
const isParsing = computed(() => inquiry.value?.status === 'PARSING')
const showAnalysisButton = computed(
  () =>
    canRunAi.value &&
    Boolean(inquiry.value) &&
    (isParsing.value || ANALYZABLE_STATUSES.includes(inquiry.value!.status)),
)
const transitions = computed<InquiryStatus[]>(() => {
  if (!inquiry.value) {
    return []
  }
  return INQUIRY_STATUS_TRANSITIONS[inquiry.value.status] ?? []
})
const canTransition = computed(() => canEdit.value && transitions.value.length > 0)

function stopPolling(): void {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadCustomer(customerId: string): Promise<void> {
  if (!canReadCustomers.value) {
    return
  }
  try {
    const customer = await fetchCustomer(customerId)
    customerName.value = customer.company_name
  } catch {
    customerName.value = ''
  }
}

async function load(id: string, silent = false): Promise<void> {
  if (!silent) {
    loading.value = true
  }
  errorMessage.value = ''
  const previousStatus = inquiry.value?.status
  try {
    const detail = await fetchInquiry(id)
    const customerChanged = inquiry.value?.customer_id !== detail.customer_id
    inquiry.value = detail
    if (customerChanged || !customerName.value) {
      await loadCustomer(detail.customer_id)
    }
    if (previousStatus === 'PARSING' && detail.status !== 'PARSING') {
      stopPolling()
      refreshKey.value += 1
      if (analysisRequested.value) {
        analysisRequested.value = false
        if (detail.status === 'READY_FOR_MATCH') {
          ElMessage.success('AI 解析完成，需求字段已就绪')
        } else if (detail.status === 'NEEDS_INFO') {
          ElMessage.warning('AI 解析完成，但仍有关键字段缺失，请人工补充')
        } else {
          ElMessage.info('AI 解析结束，请查看需求字段')
        }
      }
    }
  } catch (error) {
    if (!silent) {
      inquiry.value = null
      errorMessage.value = error instanceof ApiError ? error.message : '加载询盘详情失败'
      if (!(error instanceof ApiError) || error.status !== 404) {
        ElMessage.error(errorMessage.value)
      }
    }
  } finally {
    if (!silent) {
      loading.value = false
    }
  }
}

function startPolling(): void {
  stopPolling()
  pollTimer = window.setInterval(() => {
    if (inquiryId.value) {
      void load(inquiryId.value, true)
    }
  }, 2000)
}

async function startAnalysis(): Promise<void> {
  if (!inquiry.value || isParsing.value) {
    return
  }
  analysisLoading.value = true
  try {
    await requestInquiryAnalysis(inquiry.value.id)
    inquiry.value.status = 'PARSING'
    analysisRequested.value = true
    ElMessage.info('已提交 AI 解析任务，请稍候')
    startPolling()
  } catch (error) {
    if (error instanceof ApiError) {
      const friendly: Record<string, string> = {
        INQUIRY_STATUS_NOT_ANALYZABLE: '当前询盘状态无法启动解析',
        INQUIRY_ANALYSIS_IN_PROGRESS: '已有解析任务正在执行，请稍候',
      }
      ElMessage.error(friendly[error.code] ?? error.message)
    } else {
      ElMessage.error('提交解析任务失败，请稍后重试')
    }
  } finally {
    analysisLoading.value = false
  }
}

function openStatusDialog(): void {
  if (!transitions.value.length) {
    return
  }
  targetStatus.value = transitions.value[0]
  statusVisible.value = true
}

async function submitStatus(): Promise<void> {
  if (!inquiry.value) {
    return
  }
  statusSaving.value = true
  try {
    const updated = await updateInquiry(inquiry.value.id, { status: targetStatus.value })
    inquiry.value = updated
    refreshKey.value += 1
    ElMessage.success(`询盘状态已更新为「${INQUIRY_STATUS_LABELS[updated.status]}」`)
    statusVisible.value = false
  } catch (error) {
    if (error instanceof ApiError && error.code === 'INVALID_STATUS_TRANSITION') {
      ElMessage.error('当前状态不允许该流转，请刷新后重试')
    } else {
      ElMessage.error(error instanceof ApiError ? error.message : '更新状态失败')
    }
  } finally {
    statusSaving.value = false
  }
}

function goBack(): void {
  void router.push({ name: 'inquiries' })
}

function openCustomer(): void {
  if (inquiry.value && canReadCustomers.value) {
    void router.push({ name: 'customer-detail', params: { id: inquiry.value.customer_id } })
  }
}

function handleSaved(saved: InquiryDetail): void {
  inquiry.value = saved
  void loadCustomer(saved.customer_id)
  refreshKey.value += 1
}

function handleMatchesGenerated(status: InquiryStatus): void {
  if (inquiry.value) {
    inquiry.value.status = status
  }
}

function handleAttachmentUploaded(): void {
  if (inquiry.value) {
    void load(inquiry.value.id, true)
  }
}

watch(
  inquiryId,
  (id) => {
    stopPolling()
    analysisRequested.value = false
    inquiry.value = null
    customerName.value = ''
    activeTab.value = 'body'
    if (id) {
      void load(id)
    }
  },
  { immediate: true },
)

onBeforeUnmount(stopPolling)
</script>

<template>
  <section v-loading="loading" class="detail-page">
    <el-result
      v-if="errorMessage && !inquiry"
      icon="warning"
      title="无法打开询盘"
      :sub-title="errorMessage"
    >
      <template #extra>
        <el-button type="primary" @click="goBack">返回询盘列表</el-button>
      </template>
    </el-result>

    <template v-else-if="inquiry">
      <el-card shadow="never" class="head-card">
        <div class="detail-head">
          <div class="head-left">
            <el-button text :icon="ArrowLeft" @click="goBack">返回列表</el-button>
            <div class="head-main">
              <div class="title-row">
                <h2>{{ inquiry.subject }}</h2>
                <el-tag :type="INQUIRY_STATUS_TAG[inquiry.status]" effect="plain">
                  {{ INQUIRY_STATUS_LABELS[inquiry.status] }}
                </el-tag>
              </div>
              <p class="subtitle">
                接收于 {{ formatDateTime(inquiry.received_at) }} ·
                {{ INQUIRY_SOURCE_LABELS[inquiry.source_type as InquirySourceType] }}
              </p>
            </div>
          </div>
          <div class="head-actions">
            <el-button
              v-if="showAnalysisButton"
              type="primary"
              :icon="MagicStick"
              :loading="analysisLoading || isParsing"
              :disabled="isParsing"
              @click="startAnalysis"
            >
              {{ isParsing ? '解析中…' : 'AI 解析' }}
            </el-button>
            <el-button v-if="canTransition" @click="openStatusDialog">流转状态</el-button>
            <el-button v-if="canEdit" :icon="Edit" @click="editVisible = true">编辑询盘</el-button>
          </div>
        </div>

        <el-descriptions :column="3" class="profile" border>
          <el-descriptions-item label="客户">
            <button
              v-if="canReadCustomers"
              class="customer-link"
              type="button"
              @click="openCustomer"
            >
              {{ customerName || inquiry.customer_id }}
            </button>
            <span v-else>{{ customerName || inquiry.customer_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="来源编号">
            {{ inquiry.source_ref || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="语言">{{ inquiry.language || '—' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatDateTime(inquiry.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="更新时间">
            {{ formatDateTime(inquiry.updated_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="附件数量">
            {{ inquiry.attachments.length }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never" class="body-card">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="原始内容" name="body">
            <div v-if="inquiry.raw_body" class="raw-body">{{ inquiry.raw_body }}</div>
            <el-empty v-else description="暂无原始询盘内容" />
          </el-tab-pane>
          <el-tab-pane label="需求解析" name="requirements">
            <RequirementPanel :inquiry-id="inquiry.id" :refresh-key="refreshKey" />
          </el-tab-pane>
          <el-tab-pane label="产品匹配" name="matches">
            <MatchPanel
              :inquiry-id="inquiry.id"
              :inquiry-status="inquiry.status"
              :refresh-key="refreshKey"
              @generated="handleMatchesGenerated"
            />
          </el-tab-pane>
          <el-tab-pane :label="`附件 (${inquiry.attachments.length})`" name="attachments">
            <AttachmentPanel
              :inquiry-id="inquiry.id"
              :attachments="inquiry.attachments"
              @uploaded="handleAttachmentUploaded"
            />
          </el-tab-pane>
        </el-tabs>
      </el-card>

      <InquiryFormDialog v-model="editVisible" :inquiry="inquiry" @saved="handleSaved" />

      <el-dialog v-model="statusVisible" title="流转询盘状态" width="460px">
        <el-form label-width="80px">
          <el-form-item label="当前状态">
            <el-tag :type="INQUIRY_STATUS_TAG[inquiry.status]" effect="plain">
              {{ INQUIRY_STATUS_LABELS[inquiry.status] }}
            </el-tag>
          </el-form-item>
          <el-form-item label="目标状态">
            <el-select v-model="targetStatus" style="width: 100%">
              <el-option
                v-for="status in transitions"
                :key="status"
                :label="INQUIRY_STATUS_LABELS[status]"
                :value="status"
              />
            </el-select>
          </el-form-item>
        </el-form>
        <el-alert
          v-if="targetStatus === 'ARCHIVED'"
          type="warning"
          :closable="false"
          show-icon
          title="归档后询盘不可再流转，请确认已处理完毕。"
        />
        <template #footer>
          <el-button @click="statusVisible = false">取消</el-button>
          <el-button type="primary" :loading="statusSaving" @click="submitStatus">确认流转</el-button>
        </template>
      </el-dialog>
    </template>
  </section>
</template>

<style scoped>
.detail-page {
  display: grid;
  gap: 16px;
}

.head-card,
.body-card {
  border-radius: 16px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
}

.head-left {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title-row h2 {
  margin: 0;
  color: #14213d;
  font-size: 22px;
}

.subtitle {
  margin: 6px 0 0;
  color: #8a97ad;
  font-size: 12px;
}

.head-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.profile {
  margin-top: 4px;
}

.customer-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: #4f46e5;
  font-weight: 600;
  cursor: pointer;
}

.customer-link:hover {
  text-decoration: underline;
}

.raw-body {
  white-space: pre-wrap;
  word-break: break-word;
  color: #334155;
  font-size: 13px;
  line-height: 1.7;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
}
</style>
