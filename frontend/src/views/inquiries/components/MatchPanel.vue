<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { MagicStick, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { ApiError } from '@/api/http'
import { fetchInquiryMatches, generateInquiryMatches } from '@/api/inquiries'
import {
  INQUIRY_FIELD_LABELS,
  MATCH_STATUS_LABELS,
  MATCH_STATUS_TAG,
} from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type { InquiryMatches, InquiryStatus, MatchStatus } from '@/types/inquiry'
import { formatPercent } from '@/utils/format'

const props = defineProps<{
  inquiryId: string
  inquiryStatus: InquiryStatus
  refreshKey?: number
}>()

const emit = defineEmits<{
  generated: [status: InquiryStatus]
}>()

const auth = useAuthStore()

const MATCHABLE_STATUSES: InquiryStatus[] = ['READY_FOR_MATCH', 'MATCHED']
const FIELD_TAG_COLORS: Record<string, 'success' | 'danger' | 'info'> = {
  matched: 'success',
  conflicts: 'danger',
  unknown: 'info',
}

const result = ref<InquiryMatches | null>(null)
const loading = ref(false)
const generating = ref(false)

const canGenerate = computed(
  () => auth.hasPermission('ai:run') && MATCHABLE_STATUSES.includes(props.inquiryStatus),
)
const matches = computed(() => result.value?.matches ?? [])
const statusCounts = computed(() => {
  const counts: Record<MatchStatus, number> = {
    EXACT: 0,
    POSSIBLE: 0,
    CONFLICT: 0,
    NO_MATCH: 0,
  }
  for (const match of matches.value) {
    counts[match.match_status] += 1
  }
  return counts
})
const hasMatches = computed(() => matches.value.length > 0)

function fieldLabels(fields: string[]): string {
  return fields.map((name) => INQUIRY_FIELD_LABELS[name] || name).join('、')
}

async function load(): Promise<void> {
  loading.value = true
  try {
    result.value = await fetchInquiryMatches(props.inquiryId)
  } catch (error) {
    result.value = null
    ElMessage.error(error instanceof ApiError ? error.message : '加载匹配结果失败')
  } finally {
    loading.value = false
  }
}

async function generate(): Promise<void> {
  generating.value = true
  try {
    const generated = await generateInquiryMatches(props.inquiryId)
    result.value = generated
    ElMessage.success(`已生成 ${generated.matches.length} 个候选产品`)
    emit('generated', generated.inquiry_status)
  } catch (error) {
    if (error instanceof ApiError) {
      const friendly: Record<string, string> = {
        INQUIRY_STATUS_NOT_MATCHABLE: '当前询盘状态无法生成匹配，请先完成解析或补充需求',
        REQUIREMENTS_NOT_READY: '尚无解析结果，请先运行 AI 解析',
        REQUIREMENTS_INCOMPLETE: '缺少产品品类，无法匹配，请先确认需求字段',
      }
      ElMessage.error(friendly[error.code] ?? error.message)
    } else {
      ElMessage.error('生成匹配失败，请稍后重试')
    }
  } finally {
    generating.value = false
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
  <div v-loading="loading" class="match-panel">
    <div class="match-head">
      <div class="match-summary">
        <el-tag v-if="hasMatches" type="success" effect="plain">完全匹配 {{ statusCounts.EXACT }}</el-tag>
        <el-tag v-if="hasMatches" type="primary" effect="plain">可能匹配 {{ statusCounts.POSSIBLE }}</el-tag>
        <el-tag v-if="hasMatches" type="warning" effect="plain">存在冲突 {{ statusCounts.CONFLICT }}</el-tag>
        <el-tag v-if="hasMatches" type="info" effect="plain">匹配度低 {{ statusCounts.NO_MATCH }}</el-tag>
        <span v-if="result?.schema_version" class="schema-hint">
          基于解析版本 v{{ result.schema_version }}
        </span>
      </div>
      <div class="match-actions">
        <el-button :icon="Refresh" @click="load">刷新</el-button>
        <el-button
          v-if="auth.hasPermission('ai:run')"
          type="primary"
          :icon="MagicStick"
          :loading="generating"
          :disabled="!canGenerate"
          @click="generate"
        >
          {{ hasMatches ? '重新匹配' : '生成匹配' }}
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!canGenerate && !hasMatches"
      type="info"
      :closable="false"
      show-icon
      title="当前状态暂不能生成匹配"
      description="询盘需完成 AI 解析并进入「待匹配 / 已匹配」状态后才能生成候选产品。"
    />

    <el-table v-if="hasMatches" :data="matches" row-key="id" class="match-table">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="match-detail">
            <p class="explanation">{{ row.explanation }}</p>
            <el-descriptions :column="3" border size="small">
              <el-descriptions-item label="品类">{{ row.category }}</el-descriptions-item>
              <el-descriptions-item label="标准号">{{ row.standard_code || '—' }}</el-descriptions-item>
              <el-descriptions-item label="材质">
                {{ [row.material, row.grade].filter(Boolean).join(' ') || '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="直径">
                {{ row.diameter || '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="长度">{{ row.length || '—' }}</el-descriptions-item>
              <el-descriptions-item label="表面处理">{{ row.surface_finish || '—' }}</el-descriptions-item>
              <el-descriptions-item label="销售单位">{{ row.sales_unit }}</el-descriptions-item>
              <el-descriptions-item label="MOQ">{{ row.moq ?? '—' }}</el-descriptions-item>
            </el-descriptions>
            <div class="field-tags">
              <div v-if="row.matched_fields.length" class="field-group">
                <span class="field-label">匹配字段</span>
                <el-tag
                  v-for="name in row.matched_fields"
                  :key="`matched-${name}`"
                  size="small"
                  :type="FIELD_TAG_COLORS.matched"
                  effect="plain"
                >
                  {{ INQUIRY_FIELD_LABELS[name] || name }}
                </el-tag>
              </div>
              <div v-if="row.conflict_fields.length" class="field-group">
                <span class="field-label">冲突字段</span>
                <el-tag
                  v-for="name in row.conflict_fields"
                  :key="`conflict-${name}`"
                  size="small"
                  :type="FIELD_TAG_COLORS.conflicts"
                  effect="plain"
                >
                  {{ INQUIRY_FIELD_LABELS[name] || name }}
                </el-tag>
              </div>
              <div v-if="row.unknown_fields.length" class="field-group">
                <span class="field-label">产品未提供</span>
                <el-tag
                  v-for="name in row.unknown_fields"
                  :key="`unknown-${name}`"
                  size="small"
                  :type="FIELD_TAG_COLORS.unknown"
                  effect="plain"
                >
                  {{ INQUIRY_FIELD_LABELS[name] || name }}
                </el-tag>
              </div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="产品" min-width="240">
        <template #default="{ row }">
          <div class="product-cell">
            <span class="product-code">{{ row.product_code }}</span>
            <span class="product-name">{{ row.product_name }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="MATCH_STATUS_TAG[row.match_status as MatchStatus]" effect="plain">
            {{ MATCH_STATUS_LABELS[row.match_status as MatchStatus] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="匹配度" width="100" align="center">
        <template #default="{ row }">{{ formatPercent(row.score) }}</template>
      </el-table-column>
      <el-table-column label="匹配字段" min-width="220">
        <template #default="{ row }">
          <span v-if="row.matched_fields.length">{{ fieldLabels(row.matched_fields) }}</span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="冲突字段" min-width="160">
        <template #default="{ row }">
          <span v-if="row.conflict_fields.length" class="conflict-text">
            {{ fieldLabels(row.conflict_fields) }}
          </span>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无匹配结果，点击「生成匹配」按已确认需求搜索产品目录" />
      </template>
    </el-table>

    <el-empty
      v-if="!hasMatches && canGenerate"
      description="暂无匹配结果，点击「生成匹配」按已确认需求搜索产品目录"
    />
  </div>
</template>

<style scoped>
.match-panel {
  display: grid;
  gap: 14px;
  min-height: 180px;
}

.match-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.match-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.schema-hint {
  color: #9aa6b8;
  font-size: 12px;
}

.match-actions {
  display: flex;
  gap: 8px;
}

.match-detail {
  padding: 6px 16px 14px;
}

.explanation {
  margin: 0 0 12px;
  color: #475569;
  font-size: 13px;
}

.field-tags {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.field-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.field-label {
  color: #7b879c;
  font-size: 12px;
}

.product-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.product-code {
  color: #14213d;
  font-weight: 600;
}

.product-name {
  color: #7b879c;
  font-size: 12px;
}

.conflict-text {
  color: #d97706;
}

.muted {
  color: #9aa6b8;
}
</style>
