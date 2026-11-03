import type { CustomerStatus, OverrideApprovalStatus, PriceBasis } from '@/types/customer'
import type { FollowupStatus } from '@/api/followups'
import type { InquiryStatus } from '@/api/inquiries'

export type TagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

export const CUSTOMER_STATUS_LABELS: Record<CustomerStatus, string> = {
  ACTIVE: '合作中',
  INACTIVE: '暂停',
  ARCHIVED: '已归档',
}

export const CUSTOMER_STATUS_TAG: Record<CustomerStatus, TagType> = {
  ACTIVE: 'success',
  INACTIVE: 'warning',
  ARCHIVED: 'info',
}

export const CUSTOMER_STATUS_OPTIONS = Object.entries(CUSTOMER_STATUS_LABELS).map(
  ([value, label]) => ({ value: value as CustomerStatus, label }),
)

export const PRICE_BASIS_LABELS: Record<PriceBasis, string> = {
  PER_PIECE: '按件',
  PER_KG: '按公斤',
  PER_SET: '按套',
  PER_LOT: '按批',
}

export const PRICE_BASIS_OPTIONS = Object.entries(PRICE_BASIS_LABELS).map(([value, label]) => ({
  value: value as PriceBasis,
  label,
}))

export const APPROVAL_STATUS_LABELS: Record<OverrideApprovalStatus, string> = {
  PENDING: '待审批',
  APPROVED: '已生效',
  REJECTED: '已驳回',
}

export const APPROVAL_STATUS_TAG: Record<OverrideApprovalStatus, TagType> = {
  PENDING: 'warning',
  APPROVED: 'success',
  REJECTED: 'danger',
}

export const INQUIRY_STATUS_LABELS: Record<InquiryStatus, string> = {
  RECEIVED: '已接收',
  PARSING: '解析中',
  NEEDS_INFO: '待补充',
  READY_FOR_MATCH: '待匹配',
  MATCHED: '已匹配',
  QUOTE_DRAFTED: '报价草稿',
  PENDING_APPROVAL: '待审批',
  QUOTE_APPROVED: '报价已批',
  REPLIED: '已回复',
  WON: '已成交',
  LOST: '已流失',
  ARCHIVED: '已归档',
}

export const INQUIRY_STATUS_TAG: Record<InquiryStatus, TagType> = {
  RECEIVED: 'info',
  PARSING: 'warning',
  NEEDS_INFO: 'warning',
  READY_FOR_MATCH: 'primary',
  MATCHED: 'primary',
  QUOTE_DRAFTED: 'primary',
  PENDING_APPROVAL: 'warning',
  QUOTE_APPROVED: 'success',
  REPLIED: 'success',
  WON: 'success',
  LOST: 'info',
  ARCHIVED: 'info',
}

export const FOLLOWUP_STATUS_LABELS: Record<FollowupStatus, string> = {
  PENDING: '待办',
  DONE: '已完成',
  CANCELLED: '已取消',
}

export const FOLLOWUP_STATUS_TAG: Record<FollowupStatus, TagType> = {
  PENDING: 'warning',
  DONE: 'success',
  CANCELLED: 'info',
}
