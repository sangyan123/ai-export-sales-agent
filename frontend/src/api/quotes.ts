import { getData, getEnvelope, http, ApiError } from './http'

import { QUOTE_ERROR_MESSAGES } from '@/constants/catalog'
import type {
  QuoteCreatePayload,
  QuoteDecisionPayload,
  QuoteDetail,
  QuoteDocument,
  QuoteDocumentFormat,
  QuoteExpirePayload,
  QuoteListParams,
  QuoteNotePayload,
  QuoteRecalculatePayload,
  QuoteSummary,
  QuoteVersionPayload,
} from '@/types/quote'

export type {
  PriceSourceKind,
  QuoteCreatePayload,
  QuoteDetail,
  QuoteDocumentFormat,
  QuoteEvent,
  QuoteEventType,
  QuoteItem,
  QuoteListParams,
  QuoteStatus,
  QuoteSummary,
} from '@/types/quote'

export function fetchQuotes(params: QuoteListParams = {}) {
  return getEnvelope<QuoteSummary[]>('/quotes', { params })
}

export function fetchQuote(quoteId: string) {
  return getData<QuoteDetail>(`/quotes/${quoteId}`)
}

export function createQuote(payload: QuoteCreatePayload) {
  return getData<QuoteDetail>('/quotes', { method: 'post', data: payload })
}

export function submitQuoteForApproval(quoteId: string) {
  return getData<QuoteDetail>(`/quotes/${quoteId}/submit-approval`, { method: 'post' })
}

export function approveQuote(quoteId: string, payload: QuoteDecisionPayload = {}) {
  return getData<QuoteDetail>(`/quotes/${quoteId}/approve`, { method: 'post', data: payload })
}

export function rejectQuote(quoteId: string, payload: QuoteDecisionPayload = {}) {
  return getData<QuoteDetail>(`/quotes/${quoteId}/reject`, { method: 'post', data: payload })
}

export function reviseQuote(quoteId: string) {
  return getData<QuoteDetail>(`/quotes/${quoteId}/revise`, { method: 'post' })
}

export function cancelQuote(quoteId: string, payload: QuoteNotePayload = {}) {
  return getData<QuoteDetail>(`/quotes/${quoteId}/cancel`, { method: 'post', data: payload })
}

export function sendQuote(quoteId: string, payload: QuoteNotePayload = {}) {
  return getData<QuoteDetail>(`/quotes/${quoteId}/send`, { method: 'post', data: payload })
}

export function expireQuote(quoteId: string, payload: QuoteExpirePayload = {}) {
  return getData<QuoteDetail>(`/quotes/${quoteId}/expire`, { method: 'post', data: payload })
}

export function recalculateQuote(quoteId: string, payload: QuoteRecalculatePayload = {}) {
  return getData<QuoteDetail>(`/quotes/${quoteId}/recalculate`, {
    method: 'post',
    data: payload,
  })
}

export function createQuoteVersion(quoteId: string, payload: QuoteVersionPayload = {}) {
  return getData<QuoteDetail>(`/quotes/${quoteId}/versions`, { method: 'post', data: payload })
}

export async function downloadQuoteDocument(
  quoteId: string,
  format: QuoteDocumentFormat,
): Promise<QuoteDocument> {
  const response = await http.request<Blob>({
    url: `/quotes/${quoteId}/documents`,
    method: 'post',
    params: { format },
    responseType: 'blob',
  })
  const disposition = String(response.headers['content-disposition'] ?? '')
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  return {
    blob: response.data,
    filename: match?.[1] ?? `quote-${quoteId}.${format.toLowerCase()}`,
  }
}

export function quoteErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return QUOTE_ERROR_MESSAGES[error.code] ?? error.message
  }
  return fallback
}
