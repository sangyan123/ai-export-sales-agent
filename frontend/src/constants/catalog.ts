import type { CustomerStatus, OverrideApprovalStatus } from '@/types/customer'
import type { FollowupStatus } from '@/api/followups'
import type {
  InquirySourceType,
  InquiryStatus,
  MatchStatus,
  ScanStatus,
} from '@/types/inquiry'
import type { CatalogStatus, PriceBasis, ProductCategory } from '@/types/product'
import type { PriceSourceKind, QuoteEventType, QuoteStatus } from '@/types/quote'

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

export const PRODUCT_CATEGORY_LABELS: Record<ProductCategory, string> = {
  BOLT: '螺栓',
  NUT: '螺母',
  SCREW: '螺钉',
  WASHER: '垫圈',
  OTHER: '其他',
}

export const PRODUCT_CATEGORY_TAG: Record<ProductCategory, TagType> = {
  BOLT: 'primary',
  NUT: 'success',
  SCREW: 'warning',
  WASHER: 'info',
  OTHER: 'info',
}

export const PRODUCT_CATEGORY_OPTIONS = Object.entries(PRODUCT_CATEGORY_LABELS).map(
  ([value, label]) => ({ value: value as ProductCategory, label }),
)

export const CATALOG_STATUS_LABELS: Record<CatalogStatus, string> = {
  ACTIVE: '启用',
  INACTIVE: '停用',
  ARCHIVED: '已归档',
}

export const CATALOG_STATUS_TAG: Record<CatalogStatus, TagType> = {
  ACTIVE: 'success',
  INACTIVE: 'warning',
  ARCHIVED: 'info',
}

export const CATALOG_STATUS_OPTIONS = Object.entries(CATALOG_STATUS_LABELS).map(
  ([value, label]) => ({ value: value as CatalogStatus, label }),
)


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

export const INQUIRY_STATUS_OPTIONS = Object.entries(INQUIRY_STATUS_LABELS).map(
  ([value, label]) => ({ value: value as InquiryStatus, label }),
)

export const INQUIRY_SOURCE_LABELS: Record<InquirySourceType, string> = {
  MANUAL: '手工录入',
  EMAIL: '邮件',
  UPLOAD: '上传',
  OTHER: '其他',
}

export const INQUIRY_SOURCE_OPTIONS = Object.entries(INQUIRY_SOURCE_LABELS).map(
  ([value, label]) => ({ value: value as InquirySourceType, label }),
)

export const INQUIRY_STATUS_TRANSITIONS: Record<InquiryStatus, InquiryStatus[]> = {
  RECEIVED: ['PARSING', 'NEEDS_INFO', 'READY_FOR_MATCH', 'QUOTE_DRAFTED', 'ARCHIVED'],
  PARSING: ['NEEDS_INFO', 'READY_FOR_MATCH'],
  NEEDS_INFO: ['RECEIVED', 'PARSING', 'READY_FOR_MATCH', 'ARCHIVED'],
  READY_FOR_MATCH: ['MATCHED', 'QUOTE_DRAFTED', 'NEEDS_INFO'],
  MATCHED: ['QUOTE_DRAFTED', 'NEEDS_INFO'],
  QUOTE_DRAFTED: ['PENDING_APPROVAL', 'MATCHED'],
  PENDING_APPROVAL: ['QUOTE_APPROVED', 'QUOTE_DRAFTED'],
  QUOTE_APPROVED: ['REPLIED', 'LOST'],
  REPLIED: ['WON', 'LOST', 'QUOTE_DRAFTED'],
  WON: ['ARCHIVED'],
  LOST: ['ARCHIVED'],
  ARCHIVED: [],
}

export const INQUIRY_FIELD_LABELS: Record<string, string> = {
  product_category: '产品品类',
  standard_code: '标准号',
  material: '材质',
  grade: '等级',
  diameter: '直径',
  length: '长度',
  thread_pitch: '螺距',
  surface_finish: '表面处理',
  quantity: '数量',
  unit: '单位',
  destination_country: '目的国',
  incoterm: '贸易条款',
  packaging: '包装要求',
}

export const MATCH_STATUS_LABELS: Record<MatchStatus, string> = {
  EXACT: '完全匹配',
  POSSIBLE: '可能匹配',
  CONFLICT: '存在冲突',
  NO_MATCH: '匹配度低',
}

export const MATCH_STATUS_TAG: Record<MatchStatus, TagType> = {
  EXACT: 'success',
  POSSIBLE: 'primary',
  CONFLICT: 'warning',
  NO_MATCH: 'info',
}

export const SCAN_STATUS_LABELS: Record<ScanStatus, string> = {
  PENDING: '待扫描',
  CLEAN: '已扫描',
  INFECTED: '有风险',
  FAILED: '扫描失败',
}

export const SCAN_STATUS_TAG: Record<ScanStatus, TagType> = {
  PENDING: 'info',
  CLEAN: 'success',
  INFECTED: 'danger',
  FAILED: 'warning',
}

export const QUOTE_STATUS_LABELS: Record<QuoteStatus, string> = {
  DRAFT: '草稿',
  PENDING_APPROVAL: '待审批',
  APPROVED: '已批准',
  REJECTED: '已驳回',
  SENT: '已发送',
  EXPIRED: '已过期',
  CANCELLED: '已取消',
}

export const QUOTE_STATUS_TAG: Record<QuoteStatus, TagType> = {
  DRAFT: 'primary',
  PENDING_APPROVAL: 'warning',
  APPROVED: 'success',
  REJECTED: 'danger',
  SENT: 'success',
  EXPIRED: 'info',
  CANCELLED: 'info',
}

export const QUOTE_STATUS_OPTIONS = Object.entries(QUOTE_STATUS_LABELS).map(([value, label]) => ({
  value: value as QuoteStatus,
  label,
}))

export const QUOTE_EVENT_LABELS: Record<QuoteEventType, string> = {
  CREATED: '创建报价',
  SUBMITTED: '提交审批',
  APPROVED: '审批通过',
  REJECTED: '审批驳回',
  REVISED: '报价修订',
  CANCELLED: '取消报价',
  SENT: '标记已发送',
  EXPIRED: '标记过期',
}

export const QUOTE_EVENT_COLOR: Record<QuoteEventType, string> = {
  CREATED: '#2563eb',
  SUBMITTED: '#f59e0b',
  APPROVED: '#16a34a',
  REJECTED: '#dc2626',
  REVISED: '#7c3aed',
  CANCELLED: '#64748b',
  SENT: '#0ea5e9',
  EXPIRED: '#94a3b8',
}

export const PRICE_SOURCE_LABELS: Record<PriceSourceKind, string> = {
  PRICE_LIST: '价格表',
  CUSTOMER_OVERRIDE: '客户专属价',
  CONTRACT: '合同价',
  MANUAL: '手工价',
}

export const QUOTE_CURRENCY_OPTIONS = ['USD', 'EUR', 'GBP', 'CNY', 'JPY', 'AUD', 'CAD']

export const QUOTE_TERM_LABELS: Record<string, string> = {
  incoterm: '贸易条款',
  payment_terms: '付款方式',
  lead_time: '交货期',
  shipping_cost: '运费',
  remark: '备注',
  notes: '备注',
}

export const QUOTE_ERROR_MESSAGES: Record<string, string> = {
  QUOTE_NOT_FOUND: '报价不存在或已被删除',
  QUOTE_VERSION_EXISTS: '该报价的下一版本已存在',
  QUOTE_EMPTY: '报价至少需要一个行项目',
  INVALID_QUOTE_NO: '报价编号格式不正确',
  INVALID_STATUS_TRANSITION: '当前报价状态不支持该操作，请刷新后重试',
  APPROVAL_NOT_FOUND: '未找到待审批记录',
  APPROVAL_AMBIGUOUS: '存在多条待审批记录，请联系管理员',
  SELF_APPROVAL_FORBIDDEN: '提交人不能审批自己的报价',
  VALIDITY_NOT_REACHED: '报价尚未超过有效期，无法标记过期',
  INQUIRY_NOT_FOUND: '关联询盘不存在',
  PRODUCT_NOT_FOUND: '产品不存在或已删除',
  PRODUCT_INACTIVE: '产品已停用，无法报价',
  PRICE_MISSING: '未找到有效价格，请先维护价格表或调整价格基准日',
  PRICE_EXPIRED: '所选价格已过期',
  PRICE_NOT_YET_VALID: '所选价格尚未生效',
  PRICE_LIST_INACTIVE: '价格表已停用',
  PRICE_LIST_AMBIGUOUS: '存在多个有效价格表，无法确定价格',
  CUSTOMER_PRICE_AMBIGUOUS: '客户专属价存在歧义',
  CURRENCY_MISMATCH: '报价行币种不一致',
  UNIT_CONVERSION_MISSING: '缺少单位换算规则',
  NO_ELIGIBLE_TIER: '数量未命中任何价格阶梯',
  QUANTITY_INVALID: '行项目数量必须大于 0',
  TIER_AMBIGUOUS: '价格阶梯存在歧义',
}
