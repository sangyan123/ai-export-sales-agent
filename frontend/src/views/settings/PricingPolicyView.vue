<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { ApiError } from '@/api/http'
import { fetchPricingPolicy, updatePricingPolicy } from '@/api/pricing'
import {
  MOQ_ENFORCEMENT_LABELS,
  MOQ_ENFORCEMENT_OPTIONS,
  PRICING_POLICY_ERROR_MESSAGES,
  ROUNDING_DECIMAL_PLACES_OPTIONS,
  ROUNDING_MODE_OPTIONS,
} from '@/constants/pricing'
import { useAuthStore } from '@/stores/auth'
import type {
  MoqEnforcement,
  PricingPolicy,
  PricingPolicyUpdatePayload,
  PricingRoundingMode,
} from '@/types/pricing'
import { formatDateTime } from '@/utils/format'

const auth = useAuthStore()
const canUpdate = computed(() => auth.hasPermission('pricing:update'))

const policy = ref<PricingPolicy | null>(null)
const loading = ref(false)
const saving = ref(false)

interface PolicyForm {
  rounding_mode: PricingRoundingMode
  rounding_decimal_places: number | null
  moq_enforcement: MoqEnforcement
  max_discount_percent: number
}

const form = reactive<PolicyForm>({
  rounding_mode: 'ROUND_HALF_UP',
  rounding_decimal_places: null,
  moq_enforcement: 'WARN',
  max_discount_percent: 100,
})

const roundingLabel = computed(
  () => ROUNDING_MODE_OPTIONS.find((item) => item.value === form.rounding_mode)?.label ?? '',
)
const moqLabel = computed(() => MOQ_ENFORCEMENT_LABELS[form.moq_enforcement])

function applyPolicy(data: PricingPolicy): void {
  policy.value = data
  form.rounding_mode = data.rounding_mode
  form.rounding_decimal_places = data.rounding_decimal_places
  form.moq_enforcement = data.moq_enforcement
  form.max_discount_percent = Number(data.max_discount_percent)
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return PRICING_POLICY_ERROR_MESSAGES[error.code] ?? error.message
  }
  return '操作失败，请稍后重试'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    applyPolicy(await fetchPricingPolicy())
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    loading.value = false
  }
}

function reset(): void {
  if (policy.value) {
    applyPolicy(policy.value)
  }
}

async function save(): Promise<void> {
  if (!Number.isFinite(form.max_discount_percent)) {
    ElMessage.warning('请输入 0 到 100 之间的折扣上限')
    return
  }
  const payload: PricingPolicyUpdatePayload = {
    rounding_mode: form.rounding_mode,
    rounding_decimal_places: form.rounding_decimal_places,
    moq_enforcement: form.moq_enforcement,
    max_discount_percent: form.max_discount_percent.toFixed(2),
  }

  saving.value = true
  try {
    applyPolicy(await updatePricingPolicy(payload))
    ElMessage.success('价格策略已保存')
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="policy-page" v-loading="loading && !policy">
    <el-card shadow="never" class="toolbar-card">
      <div class="page-head">
        <div>
          <h2>价格策略</h2>
          <p>统一配置报价金额舍入、MOQ 校验与折扣上限，策略对新建报价和重新计算生效。</p>
        </div>
        <el-tag v-if="policy" :type="policy.is_default ? 'info' : 'success'" effect="plain">
          {{ policy.is_default ? '使用系统默认值' : '已自定义' }}
        </el-tag>
      </div>
    </el-card>

    <el-alert
      v-if="!canUpdate"
      type="info"
      :closable="false"
      show-icon
      title="当前角色仅可查看价格策略，如需修改请联系销售经理或企业管理员。"
    />

    <el-card v-if="policy" shadow="never" class="form-card">
      <el-form :model="form" label-width="130px" :disabled="!canUpdate">
        <el-divider content-position="left">金额舍入</el-divider>
        <el-form-item label="舍入方式">
          <el-select v-model="form.rounding_mode" style="width: 320px">
            <el-option
              v-for="option in ROUNDING_MODE_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <span class="hint">当前：{{ roundingLabel }}，用于行金额与报价合计的展示金额。</span>
        </el-form-item>
        <el-form-item label="保留小数位">
          <el-select v-model="form.rounding_decimal_places" style="width: 320px">
            <el-option :value="null" label="跟随币种默认（通常 2 位）" />
            <el-option
              v-for="places in ROUNDING_DECIMAL_PLACES_OPTIONS"
              :key="places"
              :value="places"
              :label="`${places} 位小数`"
            />
          </el-select>
        </el-form-item>

        <el-divider content-position="left">MOQ 校验</el-divider>
        <el-form-item label="低于 MOQ 时">
          <el-select v-model="form.moq_enforcement" style="width: 320px">
            <el-option
              v-for="option in MOQ_ENFORCEMENT_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <span class="hint">
            当前：{{ moqLabel }}。选择“阻止创建”后，低于产品 MOQ 的报价将无法创建或重新计算。
          </span>
        </el-form-item>

        <el-divider content-position="left">折扣控制</el-divider>
        <el-form-item label="折扣上限">
          <el-input-number
            v-model="form.max_discount_percent"
            :min="0"
            :max="100"
            :precision="2"
            :step="1"
            controls-position="right"
            style="width: 200px"
          />
          <span class="percent">%</span>
          <span class="hint">
            按折扣金额占报价小计的比例计算；超出上限的报价可以保存草稿，但无法提交审批。
          </span>
        </el-form-item>

        <div v-if="canUpdate" class="actions">
          <el-button @click="reset">重置</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存策略</el-button>
        </div>
      </el-form>
      <p class="updated-at">
        <template v-if="policy.updated_at">
          最后更新：{{ formatDateTime(policy.updated_at) }}
        </template>
        <template v-else>尚未保存自定义策略，当前使用系统默认值。</template>
      </p>
    </el-card>
  </section>
</template>

<style scoped>
.policy-page {
  display: grid;
  gap: 16px;
}

.toolbar-card,
.form-card {
  border-radius: 16px;
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.page-head h2 {
  margin: 0;
  color: #14213d;
  font-size: 22px;
}

.page-head p {
  margin: 6px 0 0;
  color: #7b879c;
  font-size: 13px;
}

.hint {
  margin-left: 12px;
  color: #8a97ad;
  font-size: 12px;
}

.percent {
  margin-left: 8px;
  color: #5b6884;
  font-size: 14px;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}

.updated-at {
  margin: 12px 0 0;
  color: #9aa6b8;
  font-size: 12px;
  text-align: right;
}
</style>
