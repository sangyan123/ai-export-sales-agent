export interface AuditLogEntry {
  id: string
  actor_id: string | null
  action: string
  resource_type: string
  resource_id: string | null
  request_id: string | null
  ip_hash: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface AuditLogListParams {
  page?: number
  page_size?: number
  action?: string
  resource_type?: string
  resource_id?: string
  actor_id?: string
  created_from?: string
  created_to?: string
}
