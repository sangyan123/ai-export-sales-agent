export interface LoginPayload {
  email: string
  password: string
  tenant_slug: string
}

export interface TokenPayload {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  refresh_expires_in: number
}

export interface CurrentUser {
  id: string
  email: string
  display_name: string
  status: string
  last_login_at: string | null
  tenant: {
    id: string
    name: string | null
    slug: string | null
  }
  role: string
  permissions: string[]
}

export interface AcceptInvitationPayload {
  token: string
  display_name: string
  password: string
}

export interface AcceptInvitationResult {
  tokens: TokenPayload
  tenant_slug: string
  email: string
}
