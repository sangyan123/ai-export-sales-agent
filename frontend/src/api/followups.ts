import { FOLLOWUP_ERROR_MESSAGES } from '@/constants/catalog'
import type {
  FollowupCreatePayload,
  FollowupListParams,
  FollowupTask,
  FollowupUpdatePayload,
} from '@/types/followup'

import { ApiError, getData, getEnvelope } from './http'

export type {
  FollowupCreatePayload,
  FollowupListParams,
  FollowupSource,
  FollowupStatus,
  FollowupTask,
  FollowupTaskSummary,
  FollowupUpdatePayload,
} from '@/types/followup'

export function fetchFollowups(params: FollowupListParams = {}) {
  return getEnvelope<FollowupTask[]>('/followups', { params })
}

export function createFollowup(payload: FollowupCreatePayload) {
  return getData<FollowupTask>('/followups', { method: 'post', data: payload })
}

export function updateFollowup(taskId: string, payload: FollowupUpdatePayload) {
  return getData<FollowupTask>(`/followups/${taskId}`, { method: 'patch', data: payload })
}

export function followupErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return FOLLOWUP_ERROR_MESSAGES[error.code] ?? error.message
  }
  return fallback
}
