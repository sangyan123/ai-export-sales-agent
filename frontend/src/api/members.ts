import type { MemberListParams, MemberRole, TenantMember } from '@/types/member'

import { getData, getEnvelope } from './http'

export function fetchMembers(tenantId: string, params: MemberListParams) {
  return getEnvelope<TenantMember[]>(`/tenants/${tenantId}/members`, { params })
}

export function updateMemberRole(
  tenantId: string,
  membershipId: string,
  roleCode: MemberRole,
) {
  return getData<TenantMember>(`/tenants/${tenantId}/members/${membershipId}`, {
    method: 'patch',
    data: { role_code: roleCode },
  })
}
