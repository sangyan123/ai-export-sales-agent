import type { ApiEnvelope } from '@/types/api'
import type { CurrentUser, LoginPayload, TokenPayload } from '@/types/auth'

import { http } from './http'

export async function login(payload: LoginPayload): Promise<TokenPayload> {
  const response = await http.post<ApiEnvelope<TokenPayload>>('/auth/login', payload)
  return response.data.data
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const response = await http.get<ApiEnvelope<CurrentUser>>('/users/me')
  return response.data.data
}

export async function logout(refreshToken: string): Promise<void> {
  await http.post('/auth/logout', { refresh_token: refreshToken })
}
