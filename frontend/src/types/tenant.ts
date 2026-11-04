export type TenantStatus = 'ACTIVE' | 'SUSPENDED' | 'ARCHIVED'

export interface TenantProfile {
  id: string
  name: string
  slug: string
  status: TenantStatus
  plan_code: string | null
  contact_email: string | null
  contact_phone: string | null
  website: string | null
  address: string | null
  main_products: string | null
  export_markets: string[]
  default_currency: string
  default_language: string
  created_at: string
  updated_at: string
}

export interface TenantProfileUpdatePayload {
  name?: string
  contact_email?: string | null
  contact_phone?: string | null
  website?: string | null
  address?: string | null
  main_products?: string | null
  export_markets?: string[]
  default_currency?: string
  default_language?: string
}
