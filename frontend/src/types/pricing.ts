export type PricingRoundingMode =
  | 'ROUND_HALF_UP'
  | 'ROUND_HALF_EVEN'
  | 'ROUND_DOWN'
  | 'ROUND_UP'

export type MoqEnforcement = 'WARN' | 'BLOCK'

export interface PricingPolicy {
  id: string | null
  rounding_mode: PricingRoundingMode
  rounding_decimal_places: number | null
  moq_enforcement: MoqEnforcement
  max_discount_percent: string
  is_default: boolean
  updated_by_id: string | null
  created_at: string | null
  updated_at: string | null
}

export interface PricingPolicyUpdatePayload {
  rounding_mode: PricingRoundingMode
  rounding_decimal_places: number | null
  moq_enforcement: MoqEnforcement
  max_discount_percent: string
}
