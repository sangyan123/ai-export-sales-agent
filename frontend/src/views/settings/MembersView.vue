<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { ApiError } from '@/api/http'
import { fetchMembers, updateMemberRole } from '@/api/members'
import type { TagType } from '@/constants/catalog'
import {
  MEMBER_ERROR_MESSAGES,
  MEMBER_ROLE_LABELS,
  MEMBER_ROLE_OPTIONS,
  MEMBER_ROLE_TAG,
  MEMBERSHIP_STATUS_LABELS,
  MEMBERSHIP_STATUS_OPTIONS,
  MEMBERSHIP_STATUS_TAG,
  MEMBER_USER_STATUS_LABELS,
} from '@/constants/member'
import { useAuthStore } from '@/stores/auth'
import type {
  MemberRole,
  MembershipStatus,
  MemberUserStatus,
  TenantMember,
} from '@/types/member'
import { formatDateTime } from '@/utils/format'

const auth = useAuthStore()
const router = useRouter()

const canUpdateRole = computed(() => auth.hasPermission('member:update_role'))
const tenantId = computed(() => auth.user?.tenant.id ?? '')

const filters = reactive({
  q: '',
  role_code: '' as MemberRole | '',
  status: '' as MembershipStatus | '',
})

const rows = ref<TenantMember[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const dialogVisible = ref(false)
const selected = ref<TenantMember | null>(null)
const selectedRole = ref<MemberRole>('VIEWER')
const saving = ref(false)

const canSubmit = computed(
  () => selected.value !== null && selectedRole.value !== selected.value.role_code,
)

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return MEMBER_ERROR_MESSAGES[error.code] ?? error.message
  }
  return '操作失败，请稍后重试'
}

function roleLabel(role: MemberRole): string {
  return MEMBER_ROLE_LABELS[role]
}

function roleTag(role: MemberRole): TagType {
  return MEMBER_ROLE_TAG[role]
}

function statusLabel(status: MembershipStatus): string {
  return MEMBERSHIP_STATUS_LABELS[status]
}

function statusTag(status: MembershipStatus): TagType {
  return MEMBERSHIP_STATUS_TAG[status]
}

function userStatusLabel(status: MemberUserStatus): string {
  return MEMBER_USER_STATUS_LABELS[status]
}

async function load(): Promise<void> {
  if (!tenantId.value) {
    return
  }
  loading.value = true
  try {
    const envelope = await fetchMembers(tenantId.value, {
      page: page.value,
      page_size: pageSize.value,
      q: filters.q.trim() || undefined,
      role_code: filters.role_code || undefined,
      status: filters.status || undefined,
    })
    rows.value = envelope.data
    total.value = envelope.meta.total ?? envelope.data.length
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载成员列表失败')
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  void load()
}

function resetFilters(): void {
  filters.q = ''
  filters.role_code = ''
  filters.status = ''
  applyFilters()
}

function changePage(next: number): void {
  page.value = next
  void load()
}

function changePageSize(size: number): void {
  pageSize.value = size
  page.value = 1
  void load()
}

function openRoleDialog(member: TenantMember): void {
  selected.value = member
  selectedRole.value = member.role_code
  dialogVisible.value = true
}

async function submitRole(): Promise<void> {
  if (!selected.value || !canSubmit.value) {
    return
  }
  const member = selected.value
  saving.value = true
  try {
    const updated = await updateMemberRole(tenantId.value, member.id, selectedRole.value)
    dialogVisible.value = false
    ElMessage.success(
      `已将 ${member.display_name} 的角色调整为${roleLabel(updated.role_code)}`,
    )

    if (updated.user_id === auth.user?.id) {
      await auth.loadCurrentUser().catch(() => undefined)
      if (!auth.hasPermission('member:read')) {
        ElMessage.info('当前账号已失去成员管理权限')
        await router.replace({ name: 'dashboard' })
        return
      }
    }
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="members-page">
    <el-card shadow="never" class="toolbar-card">
      <div class="page-head">
        <div>
          <h2>成员与角色</h2>
          <p>查看企业成员并调整角色；邀请与停用能力将在后续版本提供。</p>
        </div>
        <span class="member-count">共 {{ total }} 名成员</span>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <div class="filters">
        <el-input
          v-model="filters.q"
          class="filter-search"
          placeholder="搜索邮箱或姓名"
          maxlength="100"
          clearable
          :prefix-icon="Search"
          @keyup.enter="applyFilters"
          @clear="applyFilters"
        />
        <el-select
          v-model="filters.role_code"
          placeholder="全部角色"
          clearable
          style="width: 150px"
          @change="applyFilters"
        >
          <el-option
            v-for="option in MEMBER_ROLE_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-select
          v-model="filters.status"
          placeholder="全部状态"
          clearable
          style="width: 130px"
          @change="applyFilters"
        >
          <el-option
            v-for="option in MEMBERSHIP_STATUS_OPTIONS"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-button type="primary" :icon="Search" @click="applyFilters">查询</el-button>
        <el-button :icon="Refresh" @click="resetFilters">重置</el-button>
      </div>

      <el-table v-loading="loading" :data="rows" row-key="id">
        <el-table-column label="成员" min-width="260">
          <template #default="{ row }">
            <div class="member-cell">
              <div class="member-name">
                <strong>{{ row.display_name }}</strong>
                <el-tag
                  v-if="row.user_id === auth.user?.id"
                  size="small"
                  type="primary"
                  effect="plain"
                >
                  我
                </el-tag>
                <el-tag
                  v-if="row.user_status !== 'ACTIVE'"
                  size="small"
                  type="danger"
                  effect="plain"
                >
                  {{ userStatusLabel(row.user_status) }}
                </el-tag>
              </div>
              <span class="member-email">{{ row.email }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="130" align="center">
          <template #default="{ row }">
            <el-tag :type="roleTag(row.role_code)" effect="plain">
              {{ roleLabel(row.role_code) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="成员状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" effect="plain">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="加入时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.joined_at) }}</template>
        </el-table-column>
        <el-table-column label="最近登录" width="170">
          <template #default="{ row }">{{ formatDateTime(row.last_login_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right" align="center">
          <template #default="{ row }">
            <el-button
              v-if="canUpdateRole"
              link
              type="primary"
              @click="openRoleDialog(row)"
            >
              调整角色
            </el-button>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无成员" />
        </template>
      </el-table>

      <div class="pagination">
        <el-pagination
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="changePage"
          @size-change="changePageSize"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" title="调整成员角色" width="460px">
      <div v-if="selected" class="role-dialog">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="成员">
            {{ selected.display_name }}（{{ selected.email }}）
          </el-descriptions-item>
          <el-descriptions-item label="当前角色">
            {{ roleLabel(selected.role_code) }}
          </el-descriptions-item>
          <el-descriptions-item label="成员状态">
            {{ statusLabel(selected.status) }}
          </el-descriptions-item>
        </el-descriptions>
        <el-form label-width="80px" class="role-form">
          <el-form-item label="新角色">
            <el-select v-model="selectedRole" style="width: 100%">
              <el-option
                v-for="option in MEMBER_ROLE_OPTIONS"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </el-form-item>
        </el-form>
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="不能将企业最后一名启用中的所有者降级；角色变更会写入审计日志。"
        />
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" :disabled="!canSubmit" @click="submitRole">
          确认调整
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.members-page {
  display: grid;
  gap: 16px;
}

.toolbar-card,
.table-card {
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

.member-count {
  color: #5b6884;
  font-size: 13px;
  white-space: nowrap;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.filter-search {
  width: 240px;
}

.member-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.member-name {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.member-name strong {
  color: #1b2a4a;
  font-size: 14px;
}

.member-email {
  color: #7b879c;
  font-size: 12px;
}

.muted {
  color: #9aa6b8;
}

.pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.role-dialog {
  display: grid;
  gap: 16px;
}

.role-form {
  margin-top: 4px;
}
</style>
