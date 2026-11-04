export type FollowupStatus = 'PENDING' | 'DONE' | 'CANCELLED'

export type FollowupSource = 'MANUAL' | 'RULE'

export interface FollowupTask {
  id: string
  customer_id: string
  inquiry_id: string | null
  title: string
  due_at: string
  assigned_to: string | null
  status: FollowupStatus
  source: FollowupSource
  completed_at: string | null
  created_at: string
  updated_at: string
}

export type FollowupTaskSummary = FollowupTask

export interface FollowupListParams {
  page?: number
  page_size?: number
  status?: FollowupStatus
  assigned_to?: string
  customer_id?: string
  inquiry_id?: string
  overdue?: boolean
}

export interface FollowupCreatePayload {
  customer_id: string
  inquiry_id?: string | null
  title: string
  due_at: string
  assigned_to?: string | null
}

export interface FollowupUpdatePayload {
  title?: string
  due_at?: string
  assigned_to?: string | null
  status?: FollowupStatus
}
