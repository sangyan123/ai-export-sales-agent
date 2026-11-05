import { getData, getEnvelope } from './http'

import type { AIUsageRecord, AIUsageSummary } from '@/types/ai'

export function fetchUsageSummary(params: { days?: number } = {}) {
  return getData<AIUsageSummary>('/usage/summary', { params })
}

export function fetchUsageRecords(
  params: { page?: number; page_size?: number; operation_type?: string } = {},
) {
  return getEnvelope<AIUsageRecord[]>('/usage/records', { params })
}
