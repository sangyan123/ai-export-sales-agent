import { getEnvelope } from './http'

export type FollowupStatus = 'PENDING' | 'DONE' | 'CANCELLED'

export interface FollowupTaskSummary {
  id: string
  customer_id: string
  inquiry_id: string | null
  title: string
  due_at: string
  assigned_to: string | null
  status: FollowupStatus
  source: 'MANUAL' | 'RULE'
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface FollowupListParams {
  page?: number
  page_size?: number
  status?: FollowupStatus
  assigned_to?: string
  customer_id?: string
  inquiry_id?: string
  overdue?: boolean
}

export function fetchFollowups(params: FollowupListParams = {}) {
  return getEnvelope<FollowupTaskSummary[]>('/followups', { params })
}
