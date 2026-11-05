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

export interface AIProviderConfig {
  provider: string | null
  api_key_hint: string | null
  api_key_set: boolean
  base_url: string | null
  model_id: string | null
  enabled: boolean
  last_test_at: string | null
  last_test_status: 'SUCCESS' | 'FAILED' | null
  last_test_message: string | null
  updated_at: string | null
  env_fallback?: {
    provider: string | null
    model_id: string | null
  }
}

export interface AIProviderUpdatePayload {
  provider: string
  api_key?: string | null
  base_url?: string | null
  model_id?: string | null
  enabled?: boolean
}

export interface AIProviderTestResult {
  status: 'SUCCESS' | 'FAILED'
  message: string
  tested_at: string
}
