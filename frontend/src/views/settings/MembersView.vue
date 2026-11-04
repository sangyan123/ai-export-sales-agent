<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CopyDocument, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { ApiError } from '@/api/http'
import {
  cancelMemberInvitation,
  createMemberInvitation,
  fetchMembers,
  resendMemberInvitation,
  updateMemberRole,
  updateMemberStatus,
} from '@/api/members'
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
  MemberInvitationResult,
  MemberRole,
  MembershipStatus,
  MemberUserStatus,
  TenantMember,
} from '@/types/member'
import { formatDateTime } from '@/utils/format'

const auth = useAuthStore()
const router = useRouter()

const canUpdateRole = computed(() => auth.hasPermission('member:update_role'))
const canInvite = computed(() => auth.hasPermission('member:invite'))
const canUpdateStatus = computed(() => auth.hasPermission('member:update_status'))
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

const inviteVisible = ref(false)
const inviteFormRef = ref<FormInstance>()
const inviting = ref(false)
const inviteForm = reactive({
  email: '',
  display_name: '',
  role_code: 'SALES_REP' as MemberRole,
})
const inviteRules: FormRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效邮箱', trigger: 'blur' },
  ],
  display_name: [
    { required: true, message: '请输入姓名', trigger: 'blur' },
    { min: 1, max: 120, message: '姓名长度为 1-120 个字符', trigger: 'blur' },
  ],
  role_code: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

const invitationResult = ref<MemberInvitationResult | null>(null)
const inviteLinkVisible = ref(false)
const statusSavingId = ref('')
const inviteLink = computed(() => {
  if (!invitationResult.value) {
    return ''
  }
  const url = new URL('/accept-invitation', window.location.origin)
  url.searchParams.set('token', invitationResult.value.invitation.token)
  return url.toString()
})

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

function hasRowAction(member: TenantMember): boolean {
  if (canUpdateRole.value) {
    return true
  }
  if (member.status === 'INVITED') {
    return canInvite.value
  }
  if (member.status === 'DISABLED') {
    return canUpdateStatus.value
  }
  return canUpdateStatus.value && member.user_id !== auth.user?.id
}

function openInviteDialog(): void {
  inviteForm.email = ''
  inviteForm.display_name = ''
  inviteForm.role_code = 'SALES_REP'
  invitationResult.value = null
  inviteVisible.value = true
}

function showInvitation(result: MemberInvitationResult): void {
  invitationResult.value = result
  inviteLinkVisible.value = true
}

async function submitInvite(): Promise<void> {
  if (!inviteFormRef.value) {
    return
  }
  const valid = await inviteFormRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }
  inviting.value = true
  try {
    const result = await createMemberInvitation(tenantId.value, {
      email: inviteForm.email.trim(),
      display_name: inviteForm.display_name.trim(),
      role_code: inviteForm.role_code,
    })
    inviteVisible.value = false
    showInvitation(result)
    ElMessage.success('邀请已创建')
    page.value = 1
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    inviting.value = false
  }
}

async function copyInviteLink(): Promise<void> {
  if (!inviteLink.value) {
    return
  }
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    ElMessage.success('邀请链接已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择链接复制')
  }
}

async function resendInvite(member: TenantMember): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `将重新生成 ${member.email} 的邀请链接，旧链接会立即失效。`,
      '重新发送邀请',
      { type: 'warning', confirmButtonText: '重新生成', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  statusSavingId.value = member.id
  try {
    showInvitation(await resendMemberInvitation(tenantId.value, member.id))
    ElMessage.success('新邀请链接已生成')
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    statusSavingId.value = ''
  }
}

async function cancelInvite(member: TenantMember): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `取消后 ${member.email} 的待接受成员记录将被移除，邀请链接立即失效。`,
      '取消邀请',
      { type: 'warning', confirmButtonText: '取消邀请', cancelButtonText: '保留' },
    )
  } catch {
    return
  }
  statusSavingId.value = member.id
  try {
    await cancelMemberInvitation(tenantId.value, member.id)
    ElMessage.success('邀请已取消')
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    statusSavingId.value = ''
  }
}

async function toggleStatus(member: TenantMember): Promise<void> {
  const disabling = member.status === 'ACTIVE'
  try {
    await ElMessageBox.confirm(
      disabling
        ? `停用后 ${member.display_name} 会立即退出登录，且无法再进入企业工作台。`
        : `启用后 ${member.display_name} 可以重新登录企业工作台。`,
      disabling ? '停用成员' : '启用成员',
      {
        type: 'warning',
        confirmButtonText: disabling ? '确认停用' : '确认启用',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  statusSavingId.value = member.id
  try {
    await updateMemberStatus(tenantId.value, member.id, disabling ? 'DISABLED' : 'ACTIVE')
    ElMessage.success(disabling ? `已停用 ${member.display_name}` : `已启用 ${member.display_name}`)
    await load()
  } catch (error) {
    ElMessage.error(describeError(error))
  } finally {
    statusSavingId.value = ''
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
          <p>查看企业成员，邀请新成员并管理启用状态；所有变更都会写入审计日志。</p>
        </div>
        <div class="page-actions">
          <span class="member-count">共 {{ total }} 名成员</span>
          <el-button v-if="canInvite" type="primary" :icon="Plus" @click="openInviteDialog">
            邀请成员
          </el-button>
        </div>
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
        <el-table-column label="操作" width="230" fixed="right" align="center">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button v-if="canUpdateRole" link type="primary" @click="openRoleDialog(row)">
                调整角色
              </el-button>
              <template v-if="row.status === 'INVITED'">
                <el-button
                  v-if="canInvite"
                  link
                  type="primary"
                  :loading="statusSavingId === row.id"
                  @click="resendInvite(row)"
                >
                  重新发送
                </el-button>
                <el-button
                  v-if="canInvite"
                  link
                  type="danger"
                  :loading="statusSavingId === row.id"
                  @click="cancelInvite(row)"
                >
                  取消邀请
                </el-button>
              </template>
              <template v-else>
                <el-button
                  v-if="canUpdateStatus && row.status === 'ACTIVE' && row.user_id !== auth.user?.id"
                  link
                  type="danger"
                  :loading="statusSavingId === row.id"
                  @click="toggleStatus(row)"
                >
                  停用
                </el-button>
                <el-button
                  v-if="canUpdateStatus && row.status === 'DISABLED'"
                  link
                  type="success"
                  :loading="statusSavingId === row.id"
                  @click="toggleStatus(row)"
                >
                  启用
                </el-button>
              </template>
              <span v-if="!hasRowAction(row)" class="muted">—</span>
            </div>
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

    <el-dialog v-model="inviteVisible" title="邀请成员" width="480px">
      <el-form
        ref="inviteFormRef"
        :model="inviteForm"
        :rules="inviteRules"
        label-width="76px"
        class="invite-form"
      >
        <el-form-item label="邮箱" prop="email">
          <el-input
            v-model="inviteForm.email"
            placeholder="name@company.com"
            maxlength="320"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item label="姓名" prop="display_name">
          <el-input
            v-model="inviteForm.display_name"
            placeholder="成员姓名或称呼"
            maxlength="120"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item label="角色" prop="role_code">
          <el-select v-model="inviteForm.role_code" style="width: 100%">
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
        type="info"
        :closable="false"
        show-icon
        title="系统会生成一次性邀请链接。成员打开链接并设置密码后，账号才会启用。"
      />
      <template #footer>
        <el-button @click="inviteVisible = false">取消</el-button>
        <el-button type="primary" :loading="inviting" @click="submitInvite">
          生成邀请链接
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="inviteLinkVisible" title="邀请链接" width="560px">
      <div v-if="invitationResult" class="invite-result">
        <el-alert
          type="success"
          :closable="false"
          show-icon
          title="邀请已生成。链接仅在此处展示，请通过安全渠道发送给成员。"
        />
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="成员">
            {{ invitationResult.member.display_name }}（{{ invitationResult.member.email }}）
          </el-descriptions-item>
          <el-descriptions-item label="角色">
            {{ roleLabel(invitationResult.member.role_code) }}
          </el-descriptions-item>
          <el-descriptions-item label="有效期至">
            {{ formatDateTime(invitationResult.invitation.expires_at) }}
          </el-descriptions-item>
        </el-descriptions>
        <el-input :model-value="inviteLink" readonly>
          <template #append>
            <el-button :icon="CopyDocument" @click="copyInviteLink">复制</el-button>
          </template>
        </el-input>
      </div>
      <template #footer>
        <el-button @click="inviteLinkVisible = false">关闭</el-button>
        <el-button type="primary" :icon="CopyDocument" @click="copyInviteLink">
          复制链接
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

.page-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.row-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 2px 8px;
}

.row-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.invite-form {
  margin-bottom: 4px;
}

.invite-result {
  display: grid;
  gap: 16px;
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
