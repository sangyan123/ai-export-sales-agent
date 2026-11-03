import type { TokenPayload } from '@/types/auth'

const REFRESH_TOKEN_KEY = 'fastener.refresh_token'

let accessToken: string | null = null
let refreshToken: string | null = localStorage.getItem(REFRESH_TOKEN_KEY)

export function getAccessToken(): string | null {
  return accessToken
}

export function getRefreshToken(): string | null {
  return refreshToken
}

export function setTokens(tokens: TokenPayload): void {
  accessToken = tokens.access_token
  refreshToken = tokens.refresh_token
  localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token)
}

export function clearTokens(): void {
  accessToken = null
  refreshToken = null
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}
