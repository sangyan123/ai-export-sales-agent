import { EMAIL_ERROR_MESSAGES } from '@/constants/catalog'
import type {
  EmailDraft,
  EmailDraftCreatePayload,
  EmailDraftUpdatePayload,
} from '@/types/email'

import { ApiError, getData } from './http'

export type {
  EmailDraft,
  EmailDraftCreatePayload,
  EmailDraftStatus,
  EmailDraftUpdatePayload,
} from '@/types/email'

export function generateEmailDraft(inquiryId: string, payload: EmailDraftCreatePayload = {}) {
  return getData<EmailDraft>(`/inquiries/${inquiryId}/email-drafts`, {
    method: 'post',
    data: payload,
  })
}

export function fetchEmailDraft(draftId: string) {
  return getData<EmailDraft>(`/email-drafts/${draftId}`)
}

export function updateEmailDraft(draftId: string, payload: EmailDraftUpdatePayload) {
  return getData<EmailDraft>(`/email-drafts/${draftId}`, { method: 'patch', data: payload })
}

export function approveEmailDraft(draftId: string) {
  return getData<EmailDraft>(`/email-drafts/${draftId}/approve`, { method: 'post' })
}

export function emailDraftErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return EMAIL_ERROR_MESSAGES[error.code] ?? error.message
  }
  return fallback
}
