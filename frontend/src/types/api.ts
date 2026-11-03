export interface EnvelopeMeta {
  request_id: string
  timestamp: string
  page?: number
  page_size?: number
  total?: number
}

export interface ApiEnvelope<T> {
  data: T
  meta: EnvelopeMeta
}

export interface ApiErrorDetail {
  field?: string
  reason?: string
  [key: string]: unknown
}

export interface ApiErrorPayload {
  error: {
    code: string
    message: string
    details: ApiErrorDetail[]
    request_id: string
  }
}
