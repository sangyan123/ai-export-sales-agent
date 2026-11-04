import type { TagType } from './catalog'
import type { TenantStatus } from '@/types/tenant'

export const TENANT_STATUS_LABELS: Record<TenantStatus, string> = {
  ACTIVE: '正常',
  SUSPENDED: '已暂停',
  ARCHIVED: '已归档',
}

export const TENANT_STATUS_TAG: Record<TenantStatus, TagType> = {
  ACTIVE: 'success',
  SUSPENDED: 'warning',
  ARCHIVED: 'info',
}

export const LANGUAGE_OPTIONS = [
  { value: 'en', label: 'English' },
  { value: 'zh-cn', label: '简体中文' },
  { value: 'de', label: 'Deutsch' },
  { value: 'fr', label: 'Français' },
  { value: 'es', label: 'Español' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
]

export const EXPORT_MARKET_SUGGESTIONS = [
  '北美',
  '欧洲',
  '东南亚',
  '中东',
  '南美',
  '非洲',
  '大洋洲',
  '日韩',
  '南亚',
]

export const TENANT_ERROR_MESSAGES: Record<string, string> = {
  TENANT_NOT_FOUND: '企业信息不存在，请联系平台管理员',
  FORBIDDEN: '当前角色没有修改企业资料的权限',
}
