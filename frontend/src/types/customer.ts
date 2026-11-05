export type CustomerStatus = 'ACTIVE' | 'INACTIVE' | 'ARCHIVED'

export interface Customer {
  id: string
  company_name: string
  country_code: string | null
  website: string | null
  source: string | null
  status: CustomerStatus
  owner_user_id: string | null
  created_at: string
  updated_at: string
}

export interface CustomerPayload {
  company_name: string
  country_code?: string | null
  website?: string | null
  source?: string | null
  status?: CustomerStatus
}

export interface CustomerListParams {
  page?: number
  page_size?: number
  country_code?: string
  status?: CustomerStatus
  q?: string
}

export interface Contact {
  id: string
  customer_id: string
  name: string
  email: string | null
  phone: string | null
  language: string | null
  job_title: string | null
  is_primary: boolean
  created_at: string
  updated_at: string
}

export interface ContactPayload {
  name: string
  email?: string | null
  phone?: string | null
  language?: string | null
  job_title?: string | null
  is_primary?: boolean
}

export type PriceBasis = 'PER_PIECE' | 'PER_KG' | 'PER_SET' | 'PER_LOT'
export type OverrideApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

export interface PriceOverride {
  id: string
  customer_id: string
  product_id: string
  currency: string
  unit_price: string
  price_basis: PriceBasis
  unit: string
  valid_from: string
  valid_to: string | null
  approval_status: OverrideApprovalStatus
  approved_by: string | null
  approved_at: string | null
  created_at: string
  updated_at: string
}

export interface PriceOverridePayload {
  product_id: string
  currency: string
  unit_price: string
  price_basis: PriceBasis
  unit: string
  valid_from: string
  valid_to?: string | null
}

export interface CustomerNote {
  id: string
  customer_id: string
  author_id: string | null
  content: string
  created_at: string
  updated_at: string
}

export interface CustomerNotePayload {
  content: string
}
