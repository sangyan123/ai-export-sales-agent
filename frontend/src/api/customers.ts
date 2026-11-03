import { getData, getEnvelope } from './http'

import type {
  Contact,
  ContactPayload,
  Customer,
  CustomerListParams,
  CustomerPayload,
  PriceOverride,
  PriceOverridePayload,
} from '@/types/customer'

export function fetchCustomers(params: CustomerListParams) {
  return getEnvelope<Customer[]>('/customers', { params })
}

export function fetchCustomer(customerId: string) {
  return getData<Customer>(`/customers/${customerId}`)
}

export function createCustomer(payload: CustomerPayload) {
  return getData<Customer>('/customers', { method: 'post', data: payload })
}

export function updateCustomer(customerId: string, payload: Partial<CustomerPayload>) {
  return getData<Customer>(`/customers/${customerId}`, { method: 'patch', data: payload })
}

export function fetchContacts(customerId: string, params: { page?: number; page_size?: number } = {}) {
  return getEnvelope<Contact[]>(`/customers/${customerId}/contacts`, { params })
}

export function createContact(customerId: string, payload: ContactPayload) {
  return getData<Contact>(`/customers/${customerId}/contacts`, { method: 'post', data: payload })
}

export function updateContact(customerId: string, contactId: string, payload: Partial<ContactPayload>) {
  return getData<Contact>(`/customers/${customerId}/contacts/${contactId}`, {
    method: 'patch',
    data: payload,
  })
}

export function fetchPriceOverrides(
  customerId: string,
  params: { page?: number; page_size?: number } = {},
) {
  return getEnvelope<PriceOverride[]>(`/customers/${customerId}/price-overrides`, { params })
}

export function createPriceOverride(customerId: string, payload: PriceOverridePayload) {
  return getData<PriceOverride>(`/customers/${customerId}/price-overrides`, {
    method: 'post',
    data: payload,
  })
}

export function approvePriceOverride(customerId: string, overrideId: string) {
  return getData<PriceOverride>(
    `/customers/${customerId}/price-overrides/${overrideId}/approve`,
    { method: 'post' },
  )
}

export function rejectPriceOverride(customerId: string, overrideId: string) {
  return getData<PriceOverride>(`/customers/${customerId}/price-overrides/${overrideId}/reject`, {
    method: 'post',
  })
}
