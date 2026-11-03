import { getEnvelope } from './http'

export type ProductCategory = 'BOLT' | 'NUT' | 'SCREW' | 'WASHER' | 'OTHER'

export interface ProductSummary {
  id: string
  product_code: string
  product_name: string
  category: ProductCategory
  standard_code: string | null
  material: string | null
  grade: string | null
  diameter: string | null
  length: string | null
  sales_unit: string
  moq: string | null
  status: 'ACTIVE' | 'INACTIVE' | 'ARCHIVED'
}

export interface ProductListParams {
  page?: number
  page_size?: number
  category?: ProductCategory
  status?: 'ACTIVE' | 'INACTIVE' | 'ARCHIVED'
  q?: string
}

export function fetchProducts(params: ProductListParams = {}) {
  return getEnvelope<ProductSummary[]>('/products', { params })
}
