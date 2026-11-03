export type QuoteStatus =
  | 'DRAFT'
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'REJECTED'
  | 'SENT'
  | 'EXPIRED'
  | 'CANCELLED'

export type QuoteEventType =
  | 'CREATED'
  | 'SUBMITTED'
  | 'APPROVED'
  | 'REJECTED'
  | 'REVISED'
  | 'CANCELLED'
  | 'SENT'
  | 'EXPIRED'

export type QuoteDocumentFormat = 'PDF' | 'XLSX'

export type PriceSourceKind = 'PRICE_LIST' | 'CUSTOMER_OVERRIDE' | 'CONTRACT' | 'MANUAL'

export interface QuoteSummary {
  id: string
  inquiry_id: string | null
  quote_no: string
  version_no: number
  status: QuoteStatus
  currency: string
  subtotal: string
  subtotal_display: string
  discount_total: string
  freight_total: string
  other_charges: string
  grand_total: string
  grand_total_display: string
  valid_until: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface QuoteProductSnapshot {
  product_code?: string
  product_name?: string
  category?: string
  standard_code?: string | null
  material?: string | null
  grade?: string | null
  diameter?: string | null
  length?: string | null
  thread_pitch?: string | null
  head_type?: string | null
  drive_type?: string | null
  surface_finish?: string | null
  sales_unit?: string
  moq?: string | null
  packaging?: unknown
  attributes?: Record<string, unknown>
}

export interface QuotePriceSourceRef {
  kind: PriceSourceKind
  source_id: string
  version: number | null
  detail_id: string | null
  valid_from: string
  valid_to: string | null
  tier_valid_from: string | null
  tier_valid_to: string | null
}

export interface QuoteItem {
  id: string
  line_no: number
  product_id: string | null
  product_snapshot: QuoteProductSnapshot
  quantity: string
  unit: string
  priced_quantity: string
  price_unit: string
  price_basis: string
  unit_price: string
  unit_price_display: string
  line_total: string
  line_total_display: string
  price_source_ref: QuotePriceSourceRef
}

export interface QuoteEvent {
  id: string
  event_type: QuoteEventType
  event_payload: Record<string, unknown>
  actor_id: string | null
  created_at: string
}

export interface QuoteDetail extends QuoteSummary {
  terms: Record<string, unknown>
  source_snapshot: Record<string, unknown>
  items: QuoteItem[]
  events: QuoteEvent[]
}

export interface QuoteLineCreatePayload {
  product_id: string
  quantity: string
  unit: string
}

export interface QuoteCreatePayload {
  currency: string
  items: QuoteLineCreatePayload[]
  inquiry_id?: string | null
  customer_id?: string | null
  quote_no?: string | null
  version_no?: number
  valid_until?: string | null
  terms?: Record<string, unknown>
  source_snapshot?: Record<string, unknown>
  price_as_of?: string | null
}

export interface QuoteListParams {
  page?: number
  page_size?: number
  status?: QuoteStatus
  quote_no?: string
}

export interface QuoteDecisionPayload {
  decision_note?: string | null
}

export interface QuoteNotePayload {
  note?: string | null
}

export interface QuoteRecalculatePayload {
  price_as_of?: string | null
}

export interface QuoteExpirePayload {
  as_of?: string | null
}

export interface QuoteVersionPayload {
  valid_until?: string | null
}

export interface QuoteDocument {
  blob: Blob
  filename: string
}
