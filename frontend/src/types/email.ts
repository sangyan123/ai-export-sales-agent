export type EmailDraftStatus = 'DRAFT' | 'APPROVED'

export interface EmailDraft {
  id: string
  inquiry_id: string
  quote_id: string
  subject: string
  body: string
  language: string
  status: EmailDraftStatus
  approved_by: string | null
  approved_at: string | null
  model_id: string | null
  claims_used: string[]
  missing_information: string[]
  review_flags: string[]
  created_at: string
  updated_at: string
}

export interface EmailDraftCreatePayload {
  quote_id?: string | null
  language?: string
}

export interface EmailDraftUpdatePayload {
  subject?: string
  body?: string
}
