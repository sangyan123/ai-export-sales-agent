
export type UsageOperationType = 'INQUIRY_PARSE' | 'EMAIL_GENERATE'

export interface AIUsageRecord {
  id: string
  workflow_run_id: string | null
  operation_type: UsageOperationType
  model_id: string
  provider: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  duration_ms: number
  status: string
  error_code: string | null
  requested_by: string | null
  finished_at: string | null
  created_at: string
}

export interface AIUsageSummary {
  period_days: number
  call_count: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  total_duration_ms: number
  by_operation: Record<string, { call_count: number; total_tokens: number }>
}
