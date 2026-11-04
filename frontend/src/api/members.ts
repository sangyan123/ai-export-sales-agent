import type {
  MemberInvitationResult,
  MemberInvitePayload,
  MemberListParams,
  MemberRole,
  TenantMember,
} from '@/types/member'

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

export function createMemberInvitation(tenantId: string, payload: MemberInvitePayload) {
  return getData<MemberInvitationResult>(`/tenants/${tenantId}/members/invitations`, {
    method: 'post',
    data: payload,
  })
}

export function resendMemberInvitation(tenantId: string, membershipId: string) {
  return getData<MemberInvitationResult>(
    `/tenants/${tenantId}/members/${membershipId}/invitations`,
    { method: 'post' },
  )
}

export function cancelMemberInvitation(tenantId: string, membershipId: string) {
  return getData<{ cancelled: boolean; membership_id: string }>(
    `/tenants/${tenantId}/members/${membershipId}/invitations`,
    { method: 'delete' },
  )
}

export function updateMemberStatus(
  tenantId: string,
  membershipId: string,
  status: 'ACTIVE' | 'DISABLED',
) {
  return getData<TenantMember>(`/tenants/${tenantId}/members/${membershipId}/status`, {
    method: 'patch',
    data: { status },
  })
}
