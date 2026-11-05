import { getData, getEnvelope, http } from './http'

import type {
  Product,
  ProductImportJob,
  ProductImportTemplate,
  ProductListParams,
  ProductPayload,
  ProductSummary,
  KnowledgeDocument,
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

export async function downloadProductImportTemplate(): Promise<ProductImportTemplate> {
  const response = await http.request<Blob>({
    url: '/products/import-template',
    method: 'get',
    responseType: 'blob',
  })
  const disposition = String(response.headers['content-disposition'] ?? '')
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  return {
    blob: response.data,
    filename: match?.[1] ?? 'product-import-template.xlsx',
  }
}

export function importProducts(file: File) {
  const data = new FormData()
  data.append('file', file)
  return getData<ProductImportJob>('/products/imports', { method: 'post', data })
}

// ---------------------------------------------------------------------------
// Knowledge documents (知识资料)
// ---------------------------------------------------------------------------

export function fetchKnowledgeDocuments(
  params: { page?: number; page_size?: number; source?: string; q?: string } = {},
) {
  return getEnvelope<KnowledgeDocument[]>('/knowledge-documents', { params })
}

export function uploadKnowledgeDocument(
  file: File,
  options: { source?: string; description?: string } = {},
) {
  const data = new FormData()
  data.append('file', file)
  if (options.source) data.append('source', options.source)
  if (options.description) data.append('description', options.description)
  return getData<KnowledgeDocument>('/knowledge-documents/upload', {
    method: 'post',
    data,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function deleteKnowledgeDocument(documentId: string) {
  return getData<void>(`/knowledge-documents/${documentId}`, { method: 'delete' })
}
