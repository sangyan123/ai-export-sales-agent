import { getData, getEnvelope } from './http'

import type {
  Product,
  ProductListParams,
  ProductPayload,
  ProductSummary,
} from '@/types/product'

export type { ProductSummary } from '@/types/product'

export function fetchProducts(params: ProductListParams = {}) {
  return getEnvelope<ProductSummary[]>('/products', { params })
}

export function fetchProduct(productId: string) {
  return getData<Product>(`/products/${productId}`)
}

export function createProduct(payload: ProductPayload) {
  return getData<Product>('/products', { method: 'post', data: payload })
}

export function updateProduct(productId: string, payload: Partial<ProductPayload>) {
  return getData<Product>(`/products/${productId}`, { method: 'patch', data: payload })
}
