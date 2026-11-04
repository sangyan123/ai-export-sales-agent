import type { MoqEnforcement, PricingRoundingMode } from '@/types/pricing'

export const ROUNDING_MODE_LABELS: Record<PricingRoundingMode, string> = {
  ROUND_HALF_UP: '四舍五入（默认）',
  ROUND_HALF_EVEN: '银行家舍入',
  ROUND_DOWN: '向下舍去',
  ROUND_UP: '向上进位',
}

export const ROUNDING_MODE_OPTIONS = (
  Object.entries(ROUNDING_MODE_LABELS) as [PricingRoundingMode, string][]
).map(([value, label]) => ({ value, label }))

export const ROUNDING_DECIMAL_PLACES_OPTIONS = [0, 1, 2, 3, 4]

export const MOQ_ENFORCEMENT_LABELS: Record<MoqEnforcement, string> = {
  WARN: '仅提醒',
  BLOCK: '阻止创建',
}

export const MOQ_ENFORCEMENT_OPTIONS = (
  Object.entries(MOQ_ENFORCEMENT_LABELS) as [MoqEnforcement, string][]
).map(([value, label]) => ({ value, label }))

export const PRICING_POLICY_ERROR_MESSAGES: Record<string, string> = {
  PERMISSION_DENIED: '当前角色没有修改价格策略的权限',
  VALIDATION_ERROR: '价格策略参数不符合要求，请检查后重试',
}
