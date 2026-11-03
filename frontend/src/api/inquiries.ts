import { getData, getEnvelope } from './http'

import type {
  AnalysisRequestResult,
  InquiryAttachment,
  InquiryCreatePayload,
  InquiryDetail,
  InquiryListParams,
  InquiryMatches,
  InquiryRequirement,
  InquirySummary,
  InquiryUpdatePayload,
  RequirementUpdatePayload,
} from '@/types/inquiry'

export type {
  AnalysisRequestResult,
  InquiryAttachment,
  InquiryCreatePayload,
  InquiryDetail,
  InquiryListParams,
  InquiryMatch,
  InquiryMatches,
  InquiryRequirement,
  InquirySourceType,
  InquiryStatus,
  InquirySummary,
  InquiryUpdatePayload,
  MatchStatus,
  ParsedField,
  RequirementUpdatePayload,
  ScanStatus,
} from '@/types/inquiry'

export function fetchInquiries(params: InquiryListParams = {}) {
  return getEnvelope<InquirySummary[]>('/inquiries', { params })
}

export function fetchInquiry(inquiryId: string) {
  return getData<InquiryDetail>(`/inquiries/${inquiryId}`)
}

export function createInquiry(payload: InquiryCreatePayload) {
  return getData<InquiryDetail>('/inquiries', { method: 'post', data: payload })
}

export function updateInquiry(inquiryId: string, payload: InquiryUpdatePayload) {
  return getData<InquiryDetail>(`/inquiries/${inquiryId}`, { method: 'patch', data: payload })
}

export function uploadInquiryAttachment(inquiryId: string, file: File) {
  const data = new FormData()
  data.append('file', file)
  return getData<InquiryAttachment>(`/inquiries/${inquiryId}/attachments`, {
    method: 'post',
    data,
  })
}

export function requestInquiryAnalysis(inquiryId: string) {
  return getData<AnalysisRequestResult>(`/inquiries/${inquiryId}/analysis`, { method: 'post' })
}

export function fetchInquiryRequirements(inquiryId: string) {
  return getData<InquiryRequirement | null>(`/inquiries/${inquiryId}/requirements`)
}

export function saveInquiryRequirements(inquiryId: string, payload: RequirementUpdatePayload) {
  return getData<InquiryRequirement>(`/inquiries/${inquiryId}/requirements`, {
    method: 'patch',
    data: payload,
  })
}

export function fetchInquiryMatches(inquiryId: string) {
  return getData<InquiryMatches>(`/inquiries/${inquiryId}/matches`)
}

export function generateInquiryMatches(inquiryId: string) {
  return getData<InquiryMatches>(`/inquiries/${inquiryId}/matches`, { method: 'post' })
}
