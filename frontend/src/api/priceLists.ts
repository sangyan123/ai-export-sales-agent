import { getData, getEnvelope } from './http'

import type {
  PriceList,
  PriceListDetail,
  PriceListListParams,
  PriceListPayload,
  PriceListUpdatePayload,
  PriceTier,
  PriceTierPayload,
  PriceTierUpdatePayload,
} from '@/types/product'

export function fetchPriceLists(params: PriceListListParams = {}) {
  return getEnvelope<PriceList[]>('/price-lists', { params })
}

export function fetchPriceList(priceListId: string) {
  return getData<PriceListDetail>(`/price-lists/${priceListId}`)
}

export function createPriceList(payload: PriceListPayload) {
  return getData<PriceListDetail>('/price-lists', { method: 'post', data: payload })
}

export function updatePriceList(priceListId: string, payload: PriceListUpdatePayload) {
  return getData<PriceListDetail>(`/price-lists/${priceListId}`, {
    method: 'patch',
    data: payload,
  })
}

export function createPriceTier(priceListId: string, payload: PriceTierPayload) {
  return getData<PriceTier>(`/price-lists/${priceListId}/tiers`, {
    method: 'post',
    data: payload,
  })
}

export function updatePriceTier(tierId: string, payload: PriceTierUpdatePayload) {
  return getData<PriceTier>(`/price-tiers/${tierId}`, { method: 'patch', data: payload })
}
