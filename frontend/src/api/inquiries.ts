import { getEnvelope } from './http'

export type InquiryStatus =
  | 'RECEIVED'
  | 'PARSING'
  | 'NEEDS_INFO'
  | 'READY_FOR_MATCH'
  | 'MATCHED'
  | 'QUOTE_DRAFTED'
  | 'PENDING_APPROVAL'
  | 'QUOTE_APPROVED'
  | 'REPLIED'
  | 'WON'
  | 'LOST'
  | 'ARCHIVED'

export interface InquirySummary {
  id: string
  customer_id: string
  subject: string
  source_type: 'MANUAL' | 'EMAIL' | 'UPLOAD' | 'OTHER'
  status: InquiryStatus
  owner_user_id: string | null
  received_at: string
  created_at: string
  updated_at: string
}

export interface InquiryListParams {
  page?: number
  page_size?: number
  status?: InquiryStatus
  customer_id?: string
  owner_user_id?: string
  q?: string
}

export function fetchInquiries(params: InquiryListParams = {}) {
  return getEnvelope<InquirySummary[]>('/inquiries', { params })
}
