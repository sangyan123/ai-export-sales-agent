import type { PricingPolicy, PricingPolicyUpdatePayload } from '@/types/pricing'

import { getData } from './http'

export function fetchPricingPolicy() {
  return getData<PricingPolicy>('/tenants/current/pricing-policy')
}

export function updatePricingPolicy(payload: PricingPolicyUpdatePayload) {
  return getData<PricingPolicy>('/tenants/current/pricing-policy', {
    method: 'put',
    data: payload,
  })
}
