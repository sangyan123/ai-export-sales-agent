<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { ApiError } from '@/api/http'
import { fetchInquiryRequirements, saveInquiryRequirements } from '@/api/inquiries'
import { INQUIRY_FIELD_LABELS } from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type { ConfirmedValue, InquiryRequirement, ParsedField } from '@/types/inquiry'
import { formatPercent } from '@/utils/format'

const props = defineProps<{
  inquiryId: string
  refreshKey?: number
}>()

const auth = useAuthStore()

const FIELD_ORDER = Object.keys(INQUIRY_FIELD_LABELS)
const STRING_FIELDS = new Set(['unit', 'incoterm'])

const requirement = ref<InquiryRequirement | null>(null)
const confirmedInput = ref<Record<string, string>>({})
const loading = ref(false)
const saving = ref(false)
const canEdit = computed(() => auth.hasPermission('inquiry:update'))

const overallConfidence = computed(() => {
  const parsed = requirement.value?.parsed
  if (!parsed) {
    return 0
  }
  return parsed.overall_confidence ?? requirement.value?.confidence.overall ?? 0
})

const missingFields = computed(() => requirement.value?.parsed.missing_fields ?? [])
const conflicts = computed(() => requirement.value?.parsed.conflicts ?? [])

function parsedEntry(name: string): ParsedField | null {
  if (STRING_FIELDS.has(name)) {
    return null
  }
  const parsed = requirement.value?.parsed as Record<string, unknown> | undefined
  const value = parsed?.[name]
  if (value && typeof value === 'object' && 'value' in value) {
    return value as ParsedField
  }
  return null
}

function parsedValue(name: string): string {
  if (STRING_FIELDS.has(name)) {
    const parsed = requirement.value?.parsed as Record<string, unknown> | undefined
    const value = parsed?.[name]
    return typeof value === 'string' ? value : ''
  }
  const entry = parsedEntry(name)
  return entry?.normalized_value || entry?.value || ''
}

function rawValue(name: string): string {
  const entry = parsedEntry(name)
  const value = entry?.value || ''
  return value && value !== parsedValue(name) ? value : ''
}

function confidence(name: string): number | null {
  const entry = parsedEntry(name)
  if (entry) {
    return entry.confidence
  }
  const map = requirement.value?.confidence ?? {}
  const value = map[name]
  return typeof value === 'number' ? value : null
}

function evidence(name: string): string {
  return parsedEntry(name)?.evidence || requirement.value?.evidence[name] || ''
}

function confirmedText(value: ConfirmedValue | undefined): string {
  if (!value) {
    return ''
  }
  if (typeof value === 'string') {
    return value
  }
  return value.normalized_value || value.value || ''
}

function hydrate(source: InquiryRequirement | null): void {
  requirement.value = source
  const map: Record<string, string> = {}
  for (const name of FIELD_ORDER) {
    map[name] = source ? confirmedText(source.confirmed[name]) || parsedValue(name) : ''
  }
  confirmedInput.value = map
}

async function load(): Promise<void> {
  loading.value = true
  try {
    hydrate(await fetchInquiryRequirements(props.inquiryId))
  } catch (error) {
    hydrate(null)
    ElMessage.error(error instanceof ApiError ? error.message : '加载解析结果失败')
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!requirement.value) {
    return
  }
  const confirmed: Record<string, string> = {}
  for (const name of FIELD_ORDER) {
    const value = (confirmedInput.value[name] ?? '').trim()
    if (value) {
      confirmed[name] = value
    }
  }

  saving.value = true
  try {
    const updated = await saveInquiryRequirements(props.inquiryId, {
      schema_version: requirement.value.schema_version,
      confirmed,
    })
    hydrate(updated)
    ElMessage.success('需求字段已保存')
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '保存需求字段失败')
  } finally {
    saving.value = false
  }
}

watch(
  () => props.refreshKey,
  () => {
    void load()
  },
)

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="requirement-panel">
    <el-empty v-if="!requirement && !loading" description="暂无解析结果，请先运行 AI 解析">
      <p class="empty-hint">
        解析完成后会生成带置信度和原文依据的字段清单，可在此人工确认并修正。
      </p>
    </el-empty>

    <template v-else-if="requirement">
      <div class="summary">
        <div class="summary-item">
          <span class="summary-label">整体置信度</span>
          <el-progress
            :percentage="Math.round(overallConfidence * 100)"
            :stroke-width="10"
            :status="overallConfidence >= 0.85 ? 'success' : overallConfidence >= 0.6 ? undefined : 'warning'"
            style="width: 220px"
          />
        </div>
        <div class="summary-item">
          <span class="summary-label">解析版本</span>
          <el-tag effect="plain">v{{ requirement.schema_version }}</el-tag>
        </div>
        <div v-if="requirement.model_id" class="summary-item">
          <span class="summary-label">模型</span>
          <span class="summary-value">{{ requirement.model_id }}</span>
        </div>
      </div>

      <el-alert
        v-if="missingFields.length"
        class="missing-alert"
        type="warning"
        :closable="false"
        show-icon
        title="解析发现缺失字段"
      >
        <div class="tag-row">
          <el-tag v-for="name in missingFields" :key="name" type="warning" effect="plain" size="small">
            {{ INQUIRY_FIELD_LABELS[name] || name }}
          </el-tag>
        </div>
      </el-alert>

      <el-alert
        v-if="conflicts.length"
        class="missing-alert"
        type="error"
        :closable="false"
        show-icon
        :title="`解析发现 ${conflicts.length} 处字段冲突，请人工核对`"
      />

      <el-table :data="FIELD_ORDER.map((name) => ({ name }))" row-key="name" class="field-table">
        <el-table-column label="字段" width="110">
          <template #default="{ row }">{{ INQUIRY_FIELD_LABELS[row.name] || row.name }}</template>
        </el-table-column>
        <el-table-column label="解析结果" min-width="200">
          <template #default="{ row }">
            <span>{{ parsedValue(row.name) || '—' }}</span>
            <span v-if="rawValue(row.name)" class="raw-value">（原文：{{ rawValue(row.name) }}）</span>
          </template>
        </el-table-column>
        <el-table-column label="置信度" width="100" align="center">
          <template #default="{ row }">
            <span v-if="confidence(row.name) !== null" :class="['confidence', { low: (confidence(row.name) ?? 0) < 0.6 }]">
              {{ formatPercent(confidence(row.name)) }}
            </span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="原文依据" min-width="200">
          <template #default="{ row }">
            <el-tooltip v-if="evidence(row.name)" :content="evidence(row.name)" placement="top">
              <span class="evidence">{{ evidence(row.name) }}</span>
            </el-tooltip>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="确认值" min-width="180">
          <template #default="{ row }">
            <el-input
              v-model="confirmedInput[row.name]"
              size="small"
              :disabled="!canEdit"
              placeholder="确认或修正"
            />
          </template>
        </el-table-column>
      </el-table>

      <div class="actions">
        <span class="actions-hint">确认值会保存到最新解析版本，供匹配与报价使用。</span>
        <el-button v-if="canEdit" type="primary" :loading="saving" @click="save">保存确认结果</el-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.requirement-panel {
  display: grid;
  gap: 14px;
  min-height: 180px;
}

.summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 24px;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.summary-label {
  color: #7b879c;
  font-size: 13px;
}

.summary-value {
  color: #14213d;
  font-size: 13px;
}

.missing-alert {
  margin: 0;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.field-table {
  width: 100%;
}

.raw-value {
  color: #9aa6b8;
  font-size: 12px;
}

.confidence {
  color: #16a34a;
  font-weight: 600;
}

.confidence.low {
  color: #d97706;
}

.evidence {
  display: block;
  overflow: hidden;
  color: #64748b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
}

.actions-hint {
  color: #9aa6b8;
  font-size: 12px;
}

.muted {
  color: #9aa6b8;
}

.empty-hint {
  margin: 0;
  color: #9aa6b8;
  font-size: 12px;
}
</style>
