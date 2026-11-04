import type { TagType } from './catalog'

export const AUDIT_RESOURCE_TYPE_LABELS: Record<string, string> = {
  INQUIRY: '询盘',
  QUOTE: '报价',
  PRODUCT_IMPORT: '产品导入',
  EMAIL_DRAFT: '邮件草案',
  FOLLOWUP: '跟进任务',
  TENANT: '企业',
  WORKFLOW_RUN: '工作流',
}

export const AUDIT_RESOURCE_TYPE_TAG: Record<string, TagType> = {
  INQUIRY: 'primary',
  QUOTE: 'success',
  PRODUCT_IMPORT: 'warning',
  EMAIL_DRAFT: 'info',
  FOLLOWUP: 'warning',
  TENANT: 'danger',
  WORKFLOW_RUN: 'info',
}

export const AUDIT_RESOURCE_TYPE_OPTIONS = Object.entries(AUDIT_RESOURCE_TYPE_LABELS).map(
  ([value, label]) => ({ value, label }),
)

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  'inquiry.create': '新建询盘',
  'inquiry.update': '更新询盘',
  'inquiry.attachment.upload': '上传询盘附件',
  'inquiry.analysis.request': '发起 AI 解析',
  'inquiry.analysis.completed': 'AI 解析完成',
  'inquiry.analysis.failed': 'AI 解析失败',
  'inquiry.matches.generate': '生成产品匹配',
  'quote.create': '创建报价',
  'quote.recalculate': '重算报价',
  'quote.submit': '提交审批',
  'quote.approve': '审批通过',
  'quote.reject': '审批驳回',
  'quote.revise': '创建修订版',
  'quote.create_version': '创建报价版本',
  'quote.send': '发送报价',
  'quote.expire': '标记报价过期',
  'quote.cancel': '取消报价',
  'email.draft.create': '生成邮件草案',
  'email.draft.update': '更新邮件草案',
  'email.draft.approve': '批准邮件草案',
  'followup.create': '创建跟进任务',
  'followup.update': '更新跟进任务',
  'product.import': '批量导入产品',
  'tenant.profile.updated': '更新企业资料',
  'workflow.cancel': '取消工作流',
}
