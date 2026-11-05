<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchInquiry } from '@/api/inquiries'
import {
  approveQuote,
  cancelQuote,
  createQuoteVersion,
  downloadQuoteDocument,
  expireQuote,
  fetchQuote,
  quoteErrorMessage,
  recalculateQuote,
  rejectQuote,
  reviseQuote,
  sendQuote,
  submitQuoteForApproval,
  type QuoteDetail,
  type QuoteItem,
} from '@/api/quotes'
import {
  PRICE_BASIS_LABELS,
  PRICE_SOURCE_LABELS,
  QUOTE_EVENT_COLOR,
  QUOTE_EVENT_LABELS,
  QUOTE_STATUS_LABELS,
  QUOTE_STATUS_TAG,
  QUOTE_TERM_LABELS,
} from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type { PriceBasis } from '@/types/product'
import type {
  PriceSourceKind,
  QuoteDocumentFormat,
  QuoteEvent,
  QuoteEventType,
  QuoteStatus,
} from '@/types/quote'
import { formatAmount, formatDate, formatDateTime } from '@/utils/format'

type QuoteAction =
  | 'submit'
  | 'approve'
  | 'reject'
  | 'revise'
  | 'cancel'
  | 'send'
  | 'expire'
  | 'version'
  | 'recalculate'

const ACTION_TITLES: Record<QuoteAction, string> = {
  submit: '提交审批',
  approve: '批准报价',
  reject: '驳回报价',
  revise: '重新打开报价',
  cancel: '取消报价',
  send: '标记已发送',
  expire: '标记报价过期',
  version: '新建报价版本',
  recalculate: '重新计算报价',
}

const ACTION_DESCRIPTIONS: Record<QuoteAction, string> = {
  submit: '提交后报价进入待审批状态，审批通过前不可重算。',
  approve: '批准后报价可标记为已发送，并联动关联询盘状态。',
  reject: '驳回后报价状态变为已驳回，可重新打开为草稿修改。',
  revise: '将已驳回的报价重新打开为草稿，可重算后再次提交审批。',
  cancel: '取消后报价不可继续流转或发送，请确认已与客户沟通。',
  send: '用于人工确认报价已发送给客户；导出文件本身不会改变报价状态。',
  expire: '仅在报价有效期已早于所选日期时允许标记过期。',
  version:
    '复制当前报价的全部行项目与条款，生成下一版本草稿；新版本必须重新提交审批。',
  recalculate:
    '按所选价格基准日的有效价格重算所有行项目，保留折扣、运费与其他费用。',
}

const ACTION_CONFIRM_LABELS: Record<QuoteAction, string> = {
  submit: '确认提交',
  approve: '确认批准',
  reject: '确认驳回',
  revise: '确认重新打开',
  cancel: '确认取消',
  send: '确认已发送',
  expire: '确认过期',
  version: '创建新版本',
  recalculate: '重新计算',
}

const ACTION_SUCCESS: Record<QuoteAction, string> = {
  submit: '报价已提交审批',
  approve: '报价已批准',
  reject: '报价已驳回',
  revise: '报价已重新打开为草稿',
  cancel: '报价已取消',
  send: '报价已标记为已发送',
  expire: '报价已标记为过期',
  version: '新版本已创建',
  recalculate: '报价已重新计算',
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const quote = ref<QuoteDetail | null>(null)
const inquirySubject = ref('')
const loading = ref(false)
const errorMessage = ref('')
const activeTab = ref('items')
const downloading = ref<QuoteDocumentFormat | null>(null)

const action = ref<QuoteAction | null>(null)
const actionNote = ref('')
const actionDate = ref('')
const actionSaving = ref(false)

const quoteId = computed(() => String(route.params.id ?? ''))
const status = computed<QuoteStatus | null>(() => quote.value?.status ?? null)
const canReadInquiries = computed(() => auth.hasPermission('inquiry:read'))

const canSubmit = computed(
  () => auth.hasPermission('quote:submit') && status.value === 'DRAFT',
)
const canRecalculate = computed(
  () => auth.hasPermission('quote:calculate') && status.value === 'DRAFT',
)
const canApprove = computed(
  () => auth.hasPermission('quote:approve') && status.value === 'PENDING_APPROVAL',
)
const canRevise = computed(
  () => auth.hasPermission('quote:create') && status.value === 'REJECTED',
)
const canSend = computed(
  () => auth.hasPermission('quote:submit') && status.value === 'APPROVED',
)
const canCreateVersion = computed(
  () =>
    auth.hasPermission('quote:create') &&
    ['APPROVED', 'SENT', 'EXPIRED'].includes(status.value ?? ''),
)
const canCancel = computed(
  () =>
    auth.hasPermission('quote:cancel') && ['DRAFT', 'APPROVED'].includes(status.value ?? ''),
)
const canExpire = computed(
  () =>
    auth.hasPermission('quote:cancel') &&
    ['APPROVED', 'SENT'].includes(status.value ?? '') &&
    Boolean(quote.value?.valid_until),
)
const showCreatorWarning = computed(
  () =>
    (action.value === 'approve' || action.value === 'reject') &&
    Boolean(quote.value?.created_by) &&
    quote.value?.created_by === auth.user?.id,
)

const actionVisible = computed({
  get: () => action.value !== null,
  set: (value: boolean) => {
    if (!value) {
      action.value = null
    }
  },
})
const actionTitle = computed(() => (action.value ? ACTION_TITLES[action.value] : ''))
const actionDescription = computed(() =>
  action.value ? ACTION_DESCRIPTIONS[action.value] : '',
)
const actionConfirmLabel = computed(() =>
  action.value ? ACTION_CONFIRM_LABELS[action.value] : '确认',
)
const actionNeedsNote = computed(
  () =>
    action.value !== null &&
    ['approve', 'reject', 'cancel', 'send'].includes(action.value),
)
const actionNeedsDate = computed(
  () =>
    action.value !== null &&
    ['expire', 'version', 'recalculate'].includes(action.value),
)
const actionDateLabel = computed(() => {
  if (action.value === 'expire') {
    return '过期日期'
  }
  if (action.value === 'version') {
    return '有效期至'
  }
  return '价格基准日'
})

const termEntries = computed(() => {
  const terms = quote.value?.terms ?? {}
  return Object.entries(terms)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => ({
      key,
      label: QUOTE_TERM_LABELS[key] ?? key,
      value: typeof value === 'string' ? value : String(value),
    }))
})

const sourceSnapshotText = computed(() => {
  const snapshot = quote.value?.source_snapshot
  if (!snapshot || Object.keys(snapshot).length === 0) {
    return ''
  }
  return JSON.stringify(snapshot, null, 2)
})

function todayString(): string {
  const now = new Date()
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 10)
}

function shortId(value: string | null | undefined): string {
  return value ? value.slice(0, 8) : '—'
}

function userLabel(userId: string | null | undefined): string {
  if (!userId) {
    return '—'
  }
  return auth.user?.id === userId ? '我' : shortId(userId)
}

function itemProduct(item: QuoteItem): string {
  const snapshot = item.product_snapshot
  if (snapshot.product_code) {
    return snapshot.product_name
      ? `${snapshot.product_code} · ${snapshot.product_name}`
      : snapshot.product_code
  }
  return item.product_id ? shortId(item.product_id) : '—'
}

function itemSpec(item: QuoteItem): string {
  const snapshot = item.product_snapshot
  const specs = [
    snapshot.standard_code,
    snapshot.material,
    snapshot.grade,
    snapshot.surface_finish,
  ].filter(Boolean)
  return specs.length ? specs.join(' · ') : '—'
}

function priceBasisLabel(value: string): string {
  return PRICE_BASIS_LABELS[value as PriceBasis] ?? value
}

function sourceLabel(kind: PriceSourceKind | undefined): string {
  return kind ? PRICE_SOURCE_LABELS[kind] ?? kind : '—'
}

function sourceTooltip(item: QuoteItem): string {
  const source = item.price_source_ref
  const version = source.version ? `v${source.version}` : '—'
  const validTo = source.valid_to ?? '长期'
  return `${sourceLabel(source.kind)} ${version} · 有效至 ${validTo}`
}

function eventNote(event: QuoteEvent): string {
  const payload = event.event_payload
  const note = payload.note ?? payload.decision_note
  return typeof note === 'string' ? note : ''
}

function eventMeta(event: QuoteEvent): string {
  const payload = event.event_payload
  const parts: string[] = []
  if (payload.action === 'recalculate') {
    parts.push('重新计算')
  }
  if (typeof payload.price_as_of === 'string') {
    parts.push(`价格基准日 ${payload.price_as_of}`)
  }
  if (typeof payload.as_of === 'string') {
    parts.push(`截止 ${payload.as_of}`)
  }
  if (typeof payload.version_no === 'number') {
    parts.push(`版本 v${payload.version_no}`)
  }
  if (typeof payload.grand_total === 'string') {
    parts.push(`总额 ${payload.grand_total}`)
  }
  return parts.join(' · ')
}

function openAction(kind: QuoteAction): void {
  action.value = kind
  actionNote.value = ''
  actionDate.value = ''
  if (kind === 'expire' || kind === 'recalculate') {
    actionDate.value = todayString()
  } else if (kind === 'version') {
    actionDate.value = quote.value?.valid_until ?? ''
  }
}

async function loadInquirySubject(inquiryId: string): Promise<void> {
  if (!canReadInquiries.value) {
    return
  }
  try {
    const inquiry = await fetchInquiry(inquiryId)
    inquirySubject.value = inquiry.subject
  } catch {
    inquirySubject.value = ''
  }
}

async function load(id: string): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    const detail = await fetchQuote(id)
    quote.value = detail
    inquirySubject.value = ''
    if (detail.inquiry_id) {
      void loadInquirySubject(detail.inquiry_id)
    }
  } catch (error) {
    quote.value = null
    errorMessage.value = error instanceof Error ? error.message : '加载报价详情失败'
    ElMessage.error(errorMessage.value)
  } finally {
    loading.value = false
  }
}

async function confirmAction(): Promise<void> {
  if (!quote.value || !action.value) {
    return
  }
  const currentAction = action.value
  const id = quote.value.id
  const note = actionNote.value.trim() || null

  actionSaving.value = true
  try {
    if (currentAction === 'version') {
      const version = await createQuoteVersion(id, {
        valid_until: actionDate.value || null,
      })
      action.value = null
      ElMessage.success(`已创建版本 v${version.version_no}`)
      await router.push({ name: 'quote-detail', params: { id: version.id } })
      return
    }

    let updated: QuoteDetail
    switch (currentAction) {
      case 'submit':
        updated = await submitQuoteForApproval(id)
        break
      case 'approve':
        updated = await approveQuote(id, { decision_note: note })
        break
      case 'reject':
        updated = await rejectQuote(id, { decision_note: note })
        break
      case 'revise':
        updated = await reviseQuote(id)
        break
      case 'cancel':
        updated = await cancelQuote(id, { note })
        break
      case 'send':
        updated = await sendQuote(id, { note })
        break
      case 'expire':
        updated = await expireQuote(id, { as_of: actionDate.value || null })
        break
      case 'recalculate':
        updated = await recalculateQuote(id, { price_as_of: actionDate.value || null })
        break
      default:
        return
    }

    quote.value = updated
    action.value = null
    ElMessage.success(ACTION_SUCCESS[currentAction])
  } catch (error) {
    ElMessage.error(quoteErrorMessage(error, '操作失败，请稍后重试'))
  } finally {
    actionSaving.value = false
  }
}

async function download(format: QuoteDocumentFormat): Promise<void> {
  if (!quote.value) {
    return
  }
  downloading.value = format
  try {
    const document = await downloadQuoteDocument(quote.value.id, format)
    const url = URL.createObjectURL(document.blob)
    const link = window.document.createElement('a')
    link.href = url
    link.download = document.filename
    window.document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    ElMessage.success(`已生成 ${format} 报价文件`)
  } catch (error) {
    ElMessage.error(quoteErrorMessage(error, `导出 ${format} 失败，请稍后重试`))
  } finally {
    downloading.value = null
  }
}

function goBack(): void {
  void router.push({ name: 'quotes' })
}

function openInquiry(): void {
  if (quote.value?.inquiry_id && canReadInquiries.value) {
    void router.push({ name: 'inquiry-detail', params: { id: quote.value.inquiry_id } })
  }
}

watch(
  quoteId,
  (id) => {
    quote.value = null
    inquirySubject.value = ''
    errorMessage.value = ''
    activeTab.value = 'items'
    action.value = null
    if (id) {
      void load(id)
    }
  },
  { immediate: true },
)
</script>

<template>
  <section v-loading="loading" class="detail-page">
    <el-result
      v-if="errorMessage && !quote"
      icon="warning"
      title="无法打开报价"
      :sub-title="errorMessage"
    >
      <template #extra>
        <el-button type="primary" @click="goBack">返回报价列表</el-button>
      </template>
    </el-result>

    <template v-else-if="quote">
      <el-card shadow="never" class="head-card">
        <div class="detail-head">
          <div class="head-left">
            <el-button text :icon="ArrowLeft" @click="goBack">返回列表</el-button>
            <div class="head-main">
              <div class="title-row">
                <h2>{{ quote.quote_no }}</h2>
                <el-tag effect="plain">v{{ quote.version_no }}</el-tag>
                <el-tag :type="QUOTE_STATUS_TAG[quote.status]" effect="plain">
                  {{ QUOTE_STATUS_LABELS[quote.status] }}
                </el-tag>
              </div>
              <p class="subtitle">
                创建于 {{ formatDateTime(quote.created_at) }} · 有效期至
                {{ formatDate(quote.valid_until) }}
              </p>
            </div>
          </div>

          <div class="head-actions">
            <el-button
              :icon="Download"
              :loading="downloading === 'PDF'"
              @click="download('PDF')"
            >
              PDF
            </el-button>
            <el-button
              :icon="Download"
              :loading="downloading === 'XLSX'"
              @click="download('XLSX')"
            >
              XLSX
            </el-button>
            <el-button
              v-if="canSubmit"
              type="primary"
              @click="openAction('submit')"
            >
              提交审批
            </el-button>
            <el-button v-if="canApprove" type="success" @click="openAction('approve')">
              批准
            </el-button>
            <el-button v-if="canApprove" type="danger" plain @click="openAction('reject')">
              驳回
            </el-button>
            <el-button v-if="canRevise" type="primary" @click="openAction('revise')">
              重新打开
            </el-button>
            <el-button v-if="canSend" type="primary" @click="openAction('send')">
              标记已发送
            </el-button>
            <el-button v-if="canCreateVersion" @click="openAction('version')">
              新建版本
            </el-button>
            <el-button v-if="canRecalculate" @click="openAction('recalculate')">
              重新计算
            </el-button>
            <el-button v-if="canExpire" type="warning" plain @click="openAction('expire')">
              标记过期
            </el-button>
            <el-button v-if="canCancel" type="danger" plain @click="openAction('cancel')">
              取消报价
            </el-button>
          </div>
        </div>

        <el-descriptions :column="3" class="profile" border>
          <el-descriptions-item label="关联询盘">
            <button
              v-if="quote.inquiry_id && canReadInquiries"
              class="link"
              type="button"
              @click="openInquiry"
            >
              {{ inquirySubject || shortId(quote.inquiry_id) }}
            </button>
            <span v-else>
              {{ quote.inquiry_id ? shortId(quote.inquiry_id) : '—' }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="币种">{{ quote.currency }}</el-descriptions-item>
          <el-descriptions-item label="有效期至">
            {{ formatDate(quote.valid_until) }}
          </el-descriptions-item>
          <el-descriptions-item label="创建人">
            {{ userLabel(quote.created_by) }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatDateTime(quote.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="更新时间">
            {{ formatDateTime(quote.updated_at) }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="amount-grid">
          <div class="amount-main">
            <span>报价总额</span>
            <strong>{{ formatAmount(quote.grand_total_display, quote.currency) }}</strong>
          </div>
          <div class="amount-item">
            <span>小计</span>
            <b>{{ formatAmount(quote.subtotal_display, quote.currency) }}</b>
          </div>
          <div class="amount-item">
            <span>折扣</span>
            <b>{{ formatAmount(quote.discount_total, quote.currency) }}</b>
          </div>
          <div class="amount-item">
            <span>运费</span>
            <b>{{ formatAmount(quote.freight_total, quote.currency) }}</b>
          </div>
          <div class="amount-item">
            <span>其他费用</span>
            <b>{{ formatAmount(quote.other_charges, quote.currency) }}</b>
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="body-card">
        <el-tabs v-model="activeTab">
          <el-tab-pane :label="`行项目 (${quote.items.length})`" name="items">
            <el-table :data="quote.items" row-key="id">
              <el-table-column label="行号" width="70" align="center" prop="line_no" />
              <el-table-column label="产品" min-width="260">
                <template #default="{ row }">
                  <div class="product-cell">
                    <strong>{{ itemProduct(row) }}</strong>
                    <span class="muted">{{ itemSpec(row) }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="数量" width="140" align="right">
                <template #default="{ row }">
                  {{ row.quantity }} {{ row.unit }}
                </template>
              </el-table-column>
              <el-table-column label="计价数量" width="150" align="right">
                <template #default="{ row }">
                  {{ row.priced_quantity }} {{ row.price_unit }}
                </template>
              </el-table-column>
              <el-table-column label="单价" width="170" align="right">
                <template #default="{ row }">
                  <div class="product-cell align-right">
                    <span>{{ formatAmount(row.unit_price_display, quote.currency) }}</span>
                    <span class="muted">{{ priceBasisLabel(row.price_basis) }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="金额" width="170" align="right">
                <template #default="{ row }">
                  {{ formatAmount(row.line_total_display, quote.currency) }}
                </template>
              </el-table-column>
              <el-table-column label="价格来源" width="150" align="center">
                <template #default="{ row }">
                  <el-tooltip :content="sourceTooltip(row)" placement="top">
                    <el-tag effect="plain" size="small">
                      {{ sourceLabel(row.price_source_ref.kind) }}
                    </el-tag>
                  </el-tooltip>
                </template>
              </el-table-column>
              <template #empty>
                <el-empty description="该报价没有行项目" />
              </template>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="贸易条款" name="terms">
            <el-descriptions v-if="termEntries.length" :column="2" border>
              <el-descriptions-item
                v-for="entry in termEntries"
                :key="entry.key"
                :label="entry.label"
              >
                {{ entry.value }}
              </el-descriptions-item>
            </el-descriptions>
            <el-empty v-else description="未填写贸易条款" />
            <el-collapse v-if="sourceSnapshotText" class="snapshot">
              <el-collapse-item title="来源快照（JSON）" name="snapshot">
                <pre class="snapshot-body">{{ sourceSnapshotText }}</pre>
              </el-collapse-item>
            </el-collapse>
          </el-tab-pane>

          <el-tab-pane :label="`操作记录 (${quote.events.length})`" name="events">
            <el-timeline v-if="quote.events.length" class="timeline">
              <el-timeline-item
                v-for="event in [...quote.events].reverse()"
                :key="event.id"
                :timestamp="formatDateTime(event.created_at)"
                :color="QUOTE_EVENT_COLOR[event.event_type as QuoteEventType]"
              >
                <div class="event-head">
                  <strong>{{ QUOTE_EVENT_LABELS[event.event_type as QuoteEventType] }}</strong>
                  <span class="muted">操作人 {{ userLabel(event.actor_id) }}</span>
                </div>
                <p v-if="eventMeta(event)" class="event-meta">{{ eventMeta(event) }}</p>
                <p v-if="eventNote(event)" class="event-note">备注：{{ eventNote(event) }}</p>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else description="暂无操作记录" />
          </el-tab-pane>
        </el-tabs>
      </el-card>

      <el-dialog v-model="actionVisible" :title="actionTitle" width="480px">
        <p class="action-desc">{{ actionDescription }}</p>

        <el-alert
          v-if="showCreatorWarning"
          type="warning"
          :closable="false"
          show-icon
          title="你是该报价的创建人，后端禁止提交人审批自己的报价，请由其他审批人处理。"
          class="action-alert"
        />

        <el-form label-width="90px">
          <el-form-item v-if="actionNeedsDate" :label="actionDateLabel">
            <el-date-picker
              v-model="actionDate"
              type="date"
              value-format="YYYY-MM-DD"
              clearable
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item v-if="actionNeedsNote" label="备注">
            <el-input
              v-model="actionNote"
              type="textarea"
              :rows="4"
              maxlength="4000"
              show-word-limit
              placeholder="可选，记录审批意见或操作说明"
            />
          </el-form-item>
        </el-form>

        <template #footer>
          <el-button @click="actionVisible = false">取消</el-button>
          <el-button type="primary" :loading="actionSaving" @click="confirmAction">
            {{ actionConfirmLabel }}
          </el-button>
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
  flex-wrap: wrap;
  gap: 10px;
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
  justify-content: flex-end;
  gap: 8px;
  max-width: 560px;
}

.head-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.profile {
  margin-top: 4px;
}

.link {
  padding: 0;
  border: 0;
  background: transparent;
  color: #4f46e5;
  font-weight: 600;
  cursor: pointer;
}

.link:hover {
  text-decoration: underline;
}

.amount-grid {
  display: grid;
  grid-template-columns: minmax(220px, 1.4fr) repeat(4, minmax(140px, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.amount-main,
.amount-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  border-radius: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.amount-main {
  background: linear-gradient(135deg, #eef4ff, #f8fafc);
  border-color: #dbe6ff;
}

.amount-main span,
.amount-item span {
  color: #7b879c;
  font-size: 12px;
}

.amount-main strong {
  color: #1d4ed8;
  font-size: 24px;
  line-height: 1.2;
}

.amount-item b {
  color: #14213d;
  font-size: 15px;
}

.product-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.product-cell.align-right {
  align-items: flex-end;
}

.muted {
  color: #8a97ad;
  font-size: 12px;
}

.snapshot {
  margin-top: 18px;
}

.snapshot-body {
  margin: 0;
  padding: 14px;
  border-radius: 10px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 12px;
  line-height: 1.6;
  overflow-x: auto;
}

.timeline {
  padding-top: 8px;
}

.event-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.event-meta,
.event-note {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 12px;
}

.event-note {
  color: #334155;
}

.action-desc {
  margin: 0 0 16px;
  color: #475569;
  font-size: 13px;
  line-height: 1.7;
}

.action-alert {
  margin-bottom: 16px;
}

@media (max-width: 1280px) {
  .amount-grid {
    grid-template-columns: repeat(2, minmax(140px, 1fr));
  }

  .amount-main {
    grid-column: span 2;
  }

  .detail-head {
    flex-direction: column;
  }

  .head-actions {
    justify-content: flex-start;
    max-width: none;
  }
}
</style>
