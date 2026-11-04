export type MemberRole =
  | 'OWNER'
  | 'TENANT_ADMIN'
  | 'SALES_MANAGER'
  | 'SALES_REP'
  | 'APPROVER'
  | 'VIEWER'

export type MembershipStatus = 'INVITED' | 'ACTIVE' | 'DISABLED'

export type MemberUserStatus = 'ACTIVE' | 'DISABLED'

export interface TenantMember {
  id: string
  user_id: string
  email: string
  display_name: string
  user_status: MemberUserStatus
  role_code: MemberRole
  status: MembershipStatus
  joined_at: string
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface MemberListParams {
  page: number
  page_size: number
  q?: string
  role_code?: MemberRole
  status?: MembershipStatus
}

export interface MemberInvitationLink {
  token: string
  expires_at: string
}

export interface MemberInvitationResult {
  member: TenantMember
  invitation: MemberInvitationLink
}

export interface MemberInvitePayload {
  email: string
  display_name: string
  role_code: MemberRole
}
