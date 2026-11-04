import type { AuditLogEntry, AuditLogListParams } from '@/types/audit'

import { getEnvelope } from './http'

export type { AuditLogEntry, AuditLogListParams } from '@/types/audit'

export function fetchAuditLogs(params: AuditLogListParams = {}) {
  return getEnvelope<AuditLogEntry[]>('/audit-logs', { params })
}
