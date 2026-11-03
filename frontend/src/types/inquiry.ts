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

export type InquirySourceType = 'MANUAL' | 'EMAIL' | 'UPLOAD' | 'OTHER'
export type ScanStatus = 'PENDING' | 'CLEAN' | 'INFECTED' | 'FAILED'
export type MatchStatus = 'EXACT' | 'POSSIBLE' | 'CONFLICT' | 'NO_MATCH'

export interface InquirySummary {
  id: string
  customer_id: string
  subject: string
  source_type: InquirySourceType
  status: InquiryStatus
  owner_user_id: string | null
  received_at: string
  created_at: string
  updated_at: string
}

export interface InquiryAttachment {
  id: string
  inquiry_id: string
  filename: string
  content_type: string
  size_bytes: number
  checksum: string
  scan_status: ScanStatus
  created_at: string
}

export interface InquiryDetail extends InquirySummary {
  source_ref: string | null
  raw_body: string | null
  language: string | null
  attachments: InquiryAttachment[]
}

export interface InquiryCreatePayload {
  customer_id: string
  subject: string
  source_type?: InquirySourceType
  source_ref?: string | null
  raw_body?: string | null
  language?: string | null
  received_at?: string | null
}

export interface InquiryUpdatePayload {
  customer_id?: string
  subject?: string
  source_type?: InquirySourceType
  source_ref?: string | null
  raw_body?: string | null
  language?: string | null
  status?: InquiryStatus
}

export interface InquiryListParams {
  page?: number
  page_size?: number
  status?: InquiryStatus
  customer_id?: string
  owner_user_id?: string
  q?: string
}

export interface ParsedField {
  value: string | null
  normalized_value: string | null
  confidence: number
  evidence: string | null
}

export interface InquiryParsedRequirements {
  schema_version?: string
  product_category?: ParsedField
  standard_code?: ParsedField
  material?: ParsedField
  grade?: ParsedField
  diameter?: ParsedField
  length?: ParsedField
  thread_pitch?: ParsedField
  surface_finish?: ParsedField
  quantity?: ParsedField
  unit?: string | null
  destination_country?: ParsedField
  incoterm?: string | null
  packaging?: ParsedField
  missing_fields?: string[]
  conflicts?: Record<string, unknown>[]
  overall_confidence?: number
}

export type ConfirmedValue =
  | string
  | { value?: string | null; normalized_value?: string | null }

export interface InquiryRequirement {
  id: string
  inquiry_id: string
  schema_version: number
  parsed: InquiryParsedRequirements
  confirmed: Record<string, ConfirmedValue>
  confidence: Record<string, number>
  evidence: Record<string, string>
  model_id: string | null
  created_at: string
  updated_at: string
}

export interface InquiryMatch {
  id: string
  product_id: string
  product_code: string
  product_name: string
  category: string
  standard_code: string | null
  material: string | null
  grade: string | null
  diameter: string | null
  length: string | null
  surface_finish: string | null
  sales_unit: string
  moq: string | null
  score: string
  match_status: MatchStatus
  matched_fields: string[]
  conflict_fields: string[]
  unknown_fields: string[]
  explanation: string
  created_at: string
}

export interface InquiryMatches {
  inquiry_id: string
  inquiry_status: InquiryStatus
  schema_version: number | null
  matches: InquiryMatch[]
}

export interface AnalysisRequestResult {
  workflow_run_id: string
  status: string
  inquiry_id: string
}

export interface RequirementUpdatePayload {
  schema_version: number
  confirmed: Record<string, string>
}
