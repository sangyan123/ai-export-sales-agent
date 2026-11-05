import type {
  AIProviderConfig,
  AIProviderTestResult,
  AIProviderUpdatePayload,
  TenantProfile,
  TenantProfileUpdatePayload,
} from '@/types/tenant'

import { getData } from './http'

export function fetchCurrentTenant() {
  return getData<TenantProfile>('/tenants/current')
}

export function updateCurrentTenant(payload: TenantProfileUpdatePayload) {
  return getData<TenantProfile>('/tenants/current', { method: 'patch', data: payload })
}


export function fetchAIProvider() {
  return getData<AIProviderConfig>('/settings/ai-provider')
}

export function updateAIProvider(payload: AIProviderUpdatePayload) {
  return getData<AIProviderConfig>('/settings/ai-provider', { method: 'put', data: payload })
}

export function testAIProvider() {
  return getData<AIProviderTestResult>('/settings/ai-provider/test', { method: 'post' })
}
