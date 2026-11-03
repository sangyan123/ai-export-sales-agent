export type CatalogStatus = 'ACTIVE' | 'INACTIVE' | 'ARCHIVED'
export type ProductCategory = 'BOLT' | 'NUT' | 'SCREW' | 'WASHER' | 'OTHER'
export type PriceBasis = 'PER_PIECE' | 'PER_KG' | 'PER_SET' | 'PER_LOT'

export interface Product {
  id: string
  product_code: string
  product_name: string
  category: ProductCategory
  standard_code: string | null
  material: string | null
  grade: string | null
  diameter: string | null
  length: string | null
  thread_pitch: string | null
  head_type: string | null
  drive_type: string | null
  surface_finish: string | null
  sales_unit: string
  moq: string | null
  packaging: Record<string, unknown> | null
  attributes: Record<string, unknown>
  status: CatalogStatus
  created_at: string
  updated_at: string
}

export type ProductSummary = Pick<
  Product,
  | 'id'
  | 'product_code'
  | 'product_name'
  | 'category'
  | 'standard_code'
  | 'material'
  | 'grade'
  | 'diameter'
  | 'length'
  | 'sales_unit'
  | 'moq'
  | 'status'
>

export interface ProductPayload {
  product_code: string
  product_name: string
  category: ProductCategory
  standard_code?: string | null
  material?: string | null
  grade?: string | null
  diameter?: string | null
  length?: string | null
  thread_pitch?: string | null
  head_type?: string | null
  drive_type?: string | null
  surface_finish?: string | null
  sales_unit: string
  moq?: string | null
  packaging?: Record<string, unknown> | null
  attributes?: Record<string, unknown>
  status?: CatalogStatus
}

export interface ProductListParams {
  page?: number
  page_size?: number
  category?: ProductCategory
  status?: CatalogStatus
  q?: string
}

export interface PriceTier {
  id: string
  price_list_id: string
  product_id: string
  min_quantity: string
  max_quantity: string | null
  unit_price: string
  price_basis: PriceBasis
  unit: string
  valid_from: string | null
  valid_to: string | null
  created_at: string
  updated_at: string
}

export interface PriceTierPayload {
  product_id: string
  min_quantity: string
  max_quantity?: string | null
  unit_price: string
  price_basis: PriceBasis
  unit: string
  valid_from?: string | null
  valid_to?: string | null
}

export interface PriceTierUpdatePayload {
  min_quantity?: string
  max_quantity?: string | null
  unit_price?: string
  price_basis?: PriceBasis
  unit?: string
  valid_from?: string | null
  valid_to?: string | null
}

export interface PriceList {
  id: string
  name: string
  currency: string
  valid_from: string
  valid_to: string | null
  status: CatalogStatus
  version: number
  created_at: string
  updated_at: string
}

export interface PriceListDetail extends PriceList {
  tiers: PriceTier[]
}

export interface PriceListPayload {
  name: string
  currency: string
  valid_from: string
  valid_to?: string | null
  status?: CatalogStatus
  version?: number
}

export interface PriceListUpdatePayload {
  name?: string
  valid_to?: string | null
  status?: CatalogStatus
}

export interface PriceListListParams {
  page?: number
  page_size?: number
  currency?: string
  status?: CatalogStatus
}
