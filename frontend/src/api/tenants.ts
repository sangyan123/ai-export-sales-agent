import type { TenantProfile, TenantProfileUpdatePayload } from '@/types/tenant'

import { getData } from './http'

export function fetchCurrentTenant() {
  return getData<TenantProfile>('/tenants/current')
}

export function updateCurrentTenant(payload: TenantProfileUpdatePayload) {
  return getData<TenantProfile>('/tenants/current', { method: 'patch', data: payload })
}
