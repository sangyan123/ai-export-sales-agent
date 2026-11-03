import axios, {
  type AxiosError,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'

import type { ApiEnvelope, ApiErrorDetail, ApiErrorPayload } from '@/types/api'
import type { TokenPayload } from '@/types/auth'

import { clearTokens, getAccessToken, getRefreshToken, setTokens } from './tokens'

const baseURL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

type RetryableConfig = InternalAxiosRequestConfig & { _retry?: boolean }

export class ApiError extends Error {
  status: number
  code: string
  details: ApiErrorDetail[]
  requestId: string

  constructor(
    status: number,
    code: string,
    message: string,
    details: ApiErrorDetail[] = [],
    requestId = '',
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }
}

function toApiError(error: AxiosError<ApiErrorPayload>): ApiError {
  const payload = error.response?.data?.error
  if (payload) {
    return new ApiError(
      error.response?.status ?? 0,
      payload.code,
      payload.message,
      payload.details ?? [],
      payload.request_id,
    )
  }
  if (error.code === 'ECONNABORTED') {
    return new ApiError(0, 'NETWORK_TIMEOUT', '请求超时，请稍后重试')
  }
  return new ApiError(0, 'NETWORK_ERROR', '无法连接服务器，请检查后端服务是否已启动')
}

function shouldAttemptRefresh(url: string | undefined): boolean {
  if (!url) {
    return true
  }
  return !url.includes('/auth/login') && !url.includes('/auth/refresh')
}

function redirectToLogin(): void {
  if (window.location.pathname !== '/login') {
    window.location.assign('/login?expired=1')
  }
}

export const http = axios.create({
  baseURL,
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let refreshPromise: Promise<string> | null = null

export function refreshAccessToken(): Promise<string> {
  const token = getRefreshToken()
  if (!token) {
    return Promise.reject(new Error('no refresh token'))
  }
  if (!refreshPromise) {
    refreshPromise = axios
      .post<ApiEnvelope<TokenPayload>>(
        `${baseURL}/auth/refresh`,
        { refresh_token: token },
        { timeout: 15000 },
      )
      .then((response) => {
        setTokens(response.data.data)
        return response.data.data.access_token
      })
      .finally(() => {
        refreshPromise = null
      })
  }
  return refreshPromise
}

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorPayload>) => {
    const config = error.config as RetryableConfig | undefined
    if (
      error.response?.status === 401 &&
      config &&
      !config._retry &&
      shouldAttemptRefresh(config.url)
    ) {
      config._retry = true
      try {
        const token = await refreshAccessToken()
        config.headers.Authorization = `Bearer ${token}`
        return http(config)
      } catch {
        clearTokens()
        redirectToLogin()
        return Promise.reject(toApiError(error))
      }
    }
    return Promise.reject(toApiError(error))
  },
)

export async function getEnvelope<T>(
  url: string,
  config?: AxiosRequestConfig,
): Promise<ApiEnvelope<T>> {
  const response = await http.get<ApiEnvelope<T>>(url, config)
  return response.data
}

export async function getData<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  const envelope = await getEnvelope<T>(url, config)
  return envelope.data
}
