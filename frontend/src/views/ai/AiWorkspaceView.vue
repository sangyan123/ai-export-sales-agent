<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Check, CopyDocument, Link, MagicStick } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  approveEmailDraft,
  emailDraftErrorMessage,
  fetchEmailDraft,
  generateEmailDraft,
  updateEmailDraft,
} from '@/api/emailDrafts'
import { fetchInquiries, fetchInquiry } from '@/api/inquiries'
import { fetchQuote, fetchQuotes } from '@/api/quotes'
import {
  EMAIL_LANGUAGE_OPTIONS,
  EMAIL_REVIEW_FLAG_LABELS,
  EMAIL_REVIEW_FLAG_TAG,
  EMAIL_STATUS_LABELS,
  EMAIL_STATUS_TAG,
  INQUIRY_STATUS_LABELS,
  type TagType,
} from '@/constants/catalog'
import AiUsagePanel from './components/AiUsagePanel.vue'
import { useAuthStore } from '@/stores/auth'
import type { EmailDraft } from '@/types/email'
import type { InquirySummary } from '@/types/inquiry'
import type { QuoteSummary } from '@/types/quote'
import { formatDateTime } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const inquiries = ref<InquirySummary[]>([])
const approvedQuotes = ref<QuoteSummary[]>([])
const draft = ref<EmailDraft | null>(null)
const form = reactive({ subject: '', body: '' })
const selectedInquiryId = ref('')
const selectedQuoteId = ref('')
const language = ref('en')
const draftLookup = ref('')
const generating = ref(false)
const saving = ref(false)
const approving = ref(false)
const draftLoading = ref(false)
const inquiriesLoading = ref(false)
const context = reactive({ inquirySubject: '', quoteLabel: '' })
const contextIds = reactive({ inquiry: '', quote: '' })

const canDraft = computed(() => auth.hasPermission('email:draft'))
const canUpdate = computed(() => auth.hasPermission('email:update'))
const canApprove = computed(() => auth.hasPermission('email:approve'))
const canEdit = computed(() => canUpdate.value && draft.value?.status === 'DRAFT')
const isDirty = computed(
  () =>
    !!draft.value &&
    (form.subject !== draft.value.subject || form.body !== draft.value.body),
)
const inquiryQuotes = computed(() =>
  approvedQuotes.value.filter((quote) => quote.inquiry_id === selectedInquiryId.value),
)
const languageLabel = computed(() => {
  const value = draft.value?.language
  if (!value) {
    return '—'
  }
  return EMAIL_LANGUAGE_OPTIONS.find((option) => option.value === value)?.label ?? value
})

function inquiryOptionLabel(inquiry: InquirySummary): string {
  return `${inquiry.subject} · ${INQUIRY_STATUS_LABELS[inquiry.status]}`
}

function quoteOptionLabel(quote: QuoteSummary): string {
  return `${quote.quote_no} v${quote.version_no} · ${quote.currency} ${quote.grand_total_display}`
}

function actorLabel(id: string | null): string {
  if (!id) {
    return '—'
  }
  return id === auth.user?.id ? '我' : id.slice(0, 8)
}

function reviewFlagLabel(flag: string): string {
  return EMAIL_REVIEW_FLAG_LABELS[flag] ?? flag
}

function reviewFlagType(flag: string): TagType {
  return EMAIL_REVIEW_FLAG_TAG[flag] ?? 'warning'
}

async function loadInquiries(): Promise<void> {
  inquiriesLoading.value = true
  try {
    const envelope = await fetchInquiries({ page: 1, page_size: 100 })
    inquiries.value = envelope.data
  } catch {
    inquiries.value = []
  } finally {
    inquiriesLoading.value = false
  }
}

async function loadApprovedQuotes(): Promise<void> {
  if (!canDraft.value) {
    return
  }
  try {
    const envelope = await fetchQuotes({ page: 1, page_size: 100, status: 'APPROVED' })
    approvedQuotes.value = envelope.data
  } catch {
    approvedQuotes.value = []
  }
}

async function loadContext(next: EmailDraft): Promise<void> {
  if (contextIds.inquiry !== next.inquiry_id) {
    contextIds.inquiry = next.inquiry_id
    const cached = inquiries.value.find((inquiry) => inquiry.id === next.inquiry_id)
    context.inquirySubject = cached?.subject ?? ''
    if (!cached) {
      try {
        context.inquirySubject = (await fetchInquiry(next.inquiry_id)).subject
      } catch {
        context.inquirySubject = next.inquiry_id.slice(0, 8)
      }
    }
  }
  if (contextIds.quote !== next.quote_id) {
    contextIds.quote = next.quote_id
    const cached = approvedQuotes.value.find((quote) => quote.id === next.quote_id)
    context.quoteLabel = cached ? `${cached.quote_no} v${cached.version_no}` : ''
    if (!cached) {
      try {
        const detail = await fetchQuote(next.quote_id)
        context.quoteLabel = `${detail.quote_no} v${detail.version_no}`
      } catch {
        context.quoteLabel = next.quote_id.slice(0, 8)
      }
    }
  }
}

function applyDraft(next: EmailDraft): void {
  draft.value = next
  form.subject = next.subject
  form.body = next.body
  selectedInquiryId.value = next.inquiry_id
  void loadContext(next)
}

function clearDraftState(): void {
  draft.value = null
  form.subject = ''
  form.body = ''
  context.inquirySubject = ''
  context.quoteLabel = ''
  contextIds.inquiry = ''
  contextIds.quote = ''
}

async function loadDraft(draftId: string): Promise<void> {
  draftLoading.value = true
  try {
    applyDraft(await fetchEmailDraft(draftId))
  } catch (error) {
    clearDraftState()
    ElMessage.error(emailDraftErrorMessage(error, '加载邮件草案失败'))
    if (route.query.draft_id) {
      await router.replace({ name: 'ai' })
    }
  } finally {
    draftLoading.value = false
  }
}

async function generate(): Promise<void> {
  if (!selectedInquiryId.value) {
    ElMessage.warning('请先选择询盘')
    return
  }
  generating.value = true
  try {
    const result = await generateEmailDraft(selectedInquiryId.value, {
      quote_id: selectedQuoteId.value || null,
      language: language.value,
    })
    applyDraft(result)
    ElMessage.success('邮件草案已生成')
    if (route.query.draft_id !== result.id) {
      await router.replace({ name: 'ai', query: { draft_id: result.id } })
    }
  } catch (error) {
    ElMessage.error(emailDraftErrorMessage(error, '生成邮件草案失败'))
  } finally {
    generating.value = false
  }
}

function extractDraftId(input: string): string {
  const text = input.trim()
  if (!text) {
    return ''
  }
  try {
    const url = new URL(text, window.location.origin)
    const fromQuery = url.searchParams.get('draft_id')
    if (fromQuery) {
      return fromQuery
    }
  } catch {
    // Not a URL, fall back to treating the input as a draft id.
  }
  return text
}

function openExisting(): void {
  const draftId = extractDraftId(draftLookup.value)
  if (!draftId) {
    ElMessage.warning('请输入草案链接或草案 ID')
    return
  }
  draftLookup.value = ''
  if (draftId === draft.value?.id) {
    return
  }
  void router.replace({ name: 'ai', query: { draft_id: draftId } })
}

async function save(): Promise<void> {
  if (!draft.value || !canEdit.value) {
    return
  }
  const subject = form.subject.trim()
  const body = form.body.trim()
  if (!subject) {
    ElMessage.warning('邮件主题不能为空')
    return
  }
  if (!body) {
    ElMessage.warning('邮件正文不能为空')
    return
  }
  saving.value = true
  try {
    applyDraft(await updateEmailDraft(draft.value.id, { subject, body }))
    ElMessage.success('邮件草案已保存')
  } catch (error) {
    ElMessage.error(emailDraftErrorMessage(error, '保存邮件草案失败'))
  } finally {
    saving.value = false
  }
}

function resetForm(): void {
  if (!draft.value) {
    return
  }
  form.subject = draft.value.subject
  form.body = draft.value.body
}

async function approve(): Promise<void> {
  if (!draft.value || !canApprove.value) {
    return
  }
  try {
    await ElMessageBox.confirm(
      '批准后邮件草案将锁定且不可再编辑，确认批准？',
      '批准邮件草案',
      { type: 'warning', confirmButtonText: '确认批准', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  approving.value = true
  try {
    applyDraft(await approveEmailDraft(draft.value.id))
    ElMessage.success('邮件草案已批准')
  } catch (error) {
    ElMessage.error(emailDraftErrorMessage(error, '批准邮件草案失败'))
  } finally {
    approving.value = false
  }
}

async function copyText(text: string, successMessage: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(successMessage)
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

function copyBody(): void {
  if (!draft.value) {
    return
  }
  void copyText(form.body, '邮件正文已复制')
}

async function copyLink(): Promise<void> {
  if (!draft.value) {
    return
  }
  const url = new URL(window.location.href)
  url.searchParams.set('draft_id', draft.value.id)
  await copyText(url.toString(), '草案链接已复制，可发送给审批人')
}

watch(selectedInquiryId, () => {
  selectedQuoteId.value = ''
})

watch(
  () => route.query.draft_id,
  (value) => {
    const draftId = typeof value === 'string' ? value : ''
    if (!draftId) {
      if (!draftLoading.value) {
        clearDraftState()
      }
      return
    }
    if (draftId !== draft.value?.id) {
      void loadDraft(draftId)
    }
  },
  { immediate: true },
)

onMounted(() => {
  void loadInquiries()
  void loadApprovedQuotes()
})
</script>

<template>
  <section class="ai-page">
    <el-card shadow="never" class="generator-card">
      <template #header>
        <div class="card-head">
          <div class="card-title">
            <el-icon><MagicStick /></el-icon>
            <span>生成邮件草案</span>
          </div>
          <el-tag v-if="draft" size="small" :type="EMAIL_STATUS_TAG[draft.status]" effect="plain">
            {{ EMAIL_STATUS_LABELS[draft.status] }}
          </el-tag>
        </div>
      </template>

      <el-form
        :model="{ inquiry_id: selectedInquiryId, quote_id: selectedQuoteId, language }"
        label-position="top"
        class="generator-form"
      >
        <el-form-item label="询盘">
          <el-select
            v-model="selectedInquiryId"
            placeholder="选择询盘"
            filterable
            :loading="inquiriesLoading"
            :disabled="!canDraft"
            style="width: 100%"
          >
            <el-option
              v-for="inquiry in inquiries"
              :key="inquiry.id"
              :value="inquiry.id"
              :label="inquiryOptionLabel(inquiry)"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="报价">
          <el-select
            v-model="selectedQuoteId"
            placeholder="自动使用最新已批准报价"
            :disabled="!canDraft || !selectedInquiryId"
            style="width: 100%"
          >
            <el-option label="自动：最新已批准报价" value="" />
            <el-option
              v-for="quote in inquiryQuotes"
              :key="quote.id"
              :value="quote.id"
              :label="quoteOptionLabel(quote)"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="邮件语言">
          <el-select v-model="language" :disabled="!canDraft" style="width: 100%">
            <el-option
              v-for="option in EMAIL_LANGUAGE_OPTIONS"
              :key="option.value"
              :value="option.value"
              :label="option.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="操作">
          <el-button
            type="primary"
            :icon="MagicStick"
            :loading="generating"
            :disabled="!canDraft || !selectedInquiryId"
            @click="generate"
          >
            生成草案
          </el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="canDraft"
        class="hint"
        type="info"
        :closable="false"
        show-icon
        title="生成仅使用最新已确认需求与已批准报价；缺失条款会标记为待确认，不会编造价格、折扣或交期。确定性生成器当前仅支持英文。"
      />
      <el-alert
        v-else
        class="hint"
        type="warning"
        :closable="false"
        show-icon
        title="当前角色可查看和批准邮件草案，但不能生成或编辑。请通过草案链接打开待批准内容。"
      />

      <div class="open-draft">
        <el-input
          v-model="draftLookup"
          placeholder="粘贴草案链接或草案 ID 打开已有草案"
          clearable
          @keyup.enter="openExisting"
        >
          <template #prefix>
            <el-icon><Link /></el-icon>
          </template>
        </el-input>
        <el-button @click="openExisting">打开</el-button>
      </div>
    </el-card>

    <el-card v-if="draftLoading" shadow="never" class="state-card">
      <el-skeleton :rows="8" animated />
    </el-card>
    <el-card v-else-if="!draft" shadow="never" class="state-card">
      <el-empty description="选择询盘生成邮件草案，或粘贴草案链接打开已有内容" />
    </el-card>
    <div v-else class="draft-grid">
      <el-card shadow="never" class="editor-card">
        <template #header>
          <div class="card-head">
            <div class="card-title">
              <span>邮件草案</span>
              <el-tag :type="EMAIL_STATUS_TAG[draft.status]" effect="plain">
                {{ EMAIL_STATUS_LABELS[draft.status] }}
              </el-tag>
            </div>
            <div class="head-actions">
              <el-button link type="primary" :icon="Link" @click="copyLink">
                复制草案链接
              </el-button>
              <el-button link :icon="CopyDocument" @click="copyBody">复制正文</el-button>
            </div>
          </div>
        </template>

        <div class="draft-meta">
          <span class="meta-item">
            <span class="meta-label">询盘</span>
            {{ context.inquirySubject || draft.inquiry_id.slice(0, 8) }}
          </span>
          <span class="meta-item">
            <span class="meta-label">报价</span>
            {{ context.quoteLabel || draft.quote_id.slice(0, 8) }}
          </span>
          <span class="meta-item"><span class="meta-label">语言</span>{{ languageLabel }}</span>
          <span class="meta-item">
            <span class="meta-label">更新</span>{{ formatDateTime(draft.updated_at) }}
          </span>
        </div>

        <el-form :model="form" label-position="top" class="draft-form">
          <el-form-item label="主题">
            <el-input
              v-model="form.subject"
              maxlength="240"
              show-word-limit
              :disabled="!canEdit"
            />
          </el-form-item>
          <el-form-item label="正文">
            <el-input
              v-model="form.body"
              type="textarea"
              :autosize="{ minRows: 16, maxRows: 30 }"
              :disabled="!canEdit"
              class="body-input"
            />
          </el-form-item>
        </el-form>

        <div class="editor-actions">
          <div class="left-actions">
            <el-button v-if="canEdit" :disabled="!isDirty" :loading="saving" @click="save">
              保存修改
            </el-button>
            <el-button v-if="canEdit" :disabled="!isDirty" @click="resetForm">
              撤销修改
            </el-button>
          </div>
          <el-button
            v-if="canApprove && draft.status === 'DRAFT'"
            type="primary"
            :icon="Check"
            :loading="approving"
            @click="approve"
          >
            批准草案
          </el-button>
        </div>

        <el-alert
          v-if="draft.status === 'APPROVED'"
          class="approved-note"
          type="success"
          :closable="false"
          show-icon
          :title="`已由 ${actorLabel(draft.approved_by)} 于 ${formatDateTime(draft.approved_at)} 批准，草案不可再编辑。`"
        />
        <p class="muted note">MVP 不提供真实发送接口；批准后可复制正文到邮件客户端发送。</p>
      </el-card>

      <el-card shadow="never" class="insight-card">
        <template #header>
          <div class="card-title"><span>生成洞察</span></div>
        </template>

        <div class="insight-block">
          <h4>草案信息</h4>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="模型">{{ draft.model_id || '—' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">
              {{ formatDateTime(draft.created_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="更新时间">
              {{ formatDateTime(draft.updated_at) }}
            </el-descriptions-item>
            <el-descriptions-item v-if="draft.status === 'APPROVED'" label="批准人">
              {{ actorLabel(draft.approved_by) }}
            </el-descriptions-item>
            <el-descriptions-item v-if="draft.status === 'APPROVED'" label="批准时间">
              {{ formatDateTime(draft.approved_at) }}
            </el-descriptions-item>
          </el-descriptions>
        </div>

        <div class="insight-block">
          <h4>
            缺失信息
            <el-tag
              v-if="draft.missing_information.length"
              size="small"
              type="warning"
              effect="plain"
            >
              {{ draft.missing_information.length }}
            </el-tag>
          </h4>
          <div v-if="draft.missing_information.length" class="tag-list">
            <el-tag
              v-for="item in draft.missing_information"
              :key="item"
              type="warning"
              effect="plain"
            >
              {{ item }}
            </el-tag>
          </div>
          <p v-else class="muted">无缺失信息</p>
        </div>

        <div class="insight-block">
          <h4>审核提示</h4>
          <div v-if="draft.review_flags.length" class="tag-list">
            <el-tag
              v-for="flag in draft.review_flags"
              :key="flag"
              :type="reviewFlagType(flag)"
              effect="plain"
            >
              {{ reviewFlagLabel(flag) }}
            </el-tag>
          </div>
          <p v-else class="muted">无审核提示</p>
        </div>

        <div class="insight-block">
          <h4>引用依据</h4>
          <div v-if="draft.claims_used.length" class="tag-list claims">
            <el-tag v-for="claim in draft.claims_used" :key="claim" type="info" effect="plain">
              {{ claim }}
            </el-tag>
          </div>
          <p v-else class="muted">无引用记录</p>
        </div>
      </el-card>
    </div>

    <AiUsagePanel />
  </section>
</template>

<style scoped>
.ai-page {
  display: grid;
  gap: 16px;
}

.generator-card,
.editor-card,
.insight-card,
.state-card {
  border-radius: 16px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #14213d;
  font-size: 15px;
  font-weight: 600;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.generator-form {
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) minmax(0, 1.4fr) 170px auto;
  gap: 12px;
  align-items: end;
}

.generator-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.hint {
  margin-top: 14px;
}

.open-draft {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}

.draft-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
}

.draft-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  padding: 12px 14px;
  margin-bottom: 16px;
  background: #f7f9fc;
  border-radius: 12px;
  color: #41506b;
  font-size: 13px;
}

.meta-label {
  margin-right: 4px;
  color: #8a95a9;
}

.body-input :deep(.el-textarea__inner) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  line-height: 1.6;
}

.editor-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 4px;
}

.left-actions {
  display: flex;
  gap: 8px;
}

.approved-note {
  margin-top: 16px;
}

.note {
  margin-top: 12px;
}

.insight-block {
  margin-bottom: 18px;
}

.insight-block:last-child {
  margin-bottom: 0;
}

.insight-block h4 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 10px;
  color: #14213d;
  font-size: 14px;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 180px;
  overflow: auto;
}

.tag-list.claims {
  max-height: 140px;
}

.muted {
  margin: 0;
  color: #9aa4b6;
  font-size: 13px;
}

@media (max-width: 960px) {
  .generator-form {
    grid-template-columns: 1fr;
  }

  .draft-grid {
    grid-template-columns: 1fr;
  }
}
</style>
