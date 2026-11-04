import type { TagType } from './catalog'
import type { MemberRole, MembershipStatus, MemberUserStatus } from '@/types/member'

export const MEMBER_ROLE_LABELS: Record<MemberRole, string> = {
  OWNER: '企业所有者',
  TENANT_ADMIN: '企业管理员',
  SALES_MANAGER: '销售主管',
  SALES_REP: '业务员',
  APPROVER: '审批人',
  VIEWER: '只读成员',
}

export const MEMBER_ROLE_TAG: Record<MemberRole, TagType> = {
  OWNER: 'danger',
  TENANT_ADMIN: 'warning',
  SALES_MANAGER: 'primary',
  SALES_REP: 'success',
  APPROVER: 'info',
  VIEWER: 'info',
}

export const MEMBER_ROLE_OPTIONS = Object.entries(MEMBER_ROLE_LABELS).map(([value, label]) => ({
  value: value as MemberRole,
  label,
}))

export const MEMBERSHIP_STATUS_LABELS: Record<MembershipStatus, string> = {
  INVITED: '待接受',
  ACTIVE: '正常',
  DISABLED: '已停用',
}

export const MEMBERSHIP_STATUS_TAG: Record<MembershipStatus, TagType> = {
  INVITED: 'warning',
  ACTIVE: 'success',
  DISABLED: 'info',
}

export const MEMBERSHIP_STATUS_OPTIONS = Object.entries(MEMBERSHIP_STATUS_LABELS).map(
  ([value, label]) => ({ value: value as MembershipStatus, label }),
)

export const MEMBER_USER_STATUS_LABELS: Record<MemberUserStatus, string> = {
  ACTIVE: '账号正常',
  DISABLED: '账号已停用',
}

export const MEMBER_ERROR_MESSAGES: Record<string, string> = {
  MEMBER_NOT_FOUND: '成员不存在或不属于当前企业',
  TENANT_ACCESS_DENIED: '无权访问其他企业的成员',
  LAST_OWNER_PROTECTED: '该成员是当前唯一启用中的企业所有者，不能降级',
  FORBIDDEN: '当前角色没有调整成员角色的权限',
}
