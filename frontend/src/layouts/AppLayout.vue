<script setup lang="ts">
import { computed, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowDown,
  Box,
  Calendar,
  ChatDotRound,
  Document,
  MagicStick,
  Odometer,
  Setting,
  User,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

interface MenuItem {
  path: string
  label: string
  icon: Component
  permission?: string
}

const ROLE_LABELS: Record<string, string> = {
  OWNER: '企业所有者',
  TENANT_ADMIN: '企业管理员',
  SALES_MANAGER: '销售主管',
  SALES_REP: '业务员',
  APPROVER: '审批人',
  VIEWER: '只读成员',
}

const menuItems: MenuItem[] = [
  { path: '/', label: '工作台', icon: Odometer },
  { path: '/inquiries', label: '询盘管理', icon: ChatDotRound, permission: 'inquiry:read' },
  { path: '/quotes', label: '报价中心', icon: Document, permission: 'quote:read' },
  { path: '/products', label: '产品中心', icon: Box, permission: 'product:read' },
  { path: '/customers', label: '客户管理', icon: User, permission: 'customer:read' },
  { path: '/followups', label: '跟进管理', icon: Calendar, permission: 'followup:read' },
  { path: '/ai', label: 'AI 工作台', icon: MagicStick, permission: 'workflow:read' },
  { path: '/settings', label: '企业设置', icon: Setting, permission: 'tenant:read' },
]

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const visibleMenu = computed(() =>
  menuItems.filter((item) => !item.permission || auth.hasPermission(item.permission)),
)
const pageTitle = computed(() =>
  typeof route.meta.title === 'string' ? route.meta.title : '工作台',
)
const displayName = computed(() => auth.user?.display_name ?? '未登录')
const roleLabel = computed(() => ROLE_LABELS[auth.user?.role ?? ''] ?? auth.user?.role ?? '')
const initials = computed(() => displayName.value.trim().charAt(0).toUpperCase() || 'U')

async function handleCommand(command: string): Promise<void> {
  if (command !== 'logout') {
    return
  }
  await auth.logout()
  ElMessage.success('已退出登录')
  await router.replace({ name: 'login' })
}
</script>

<template>
  <el-container class="app-shell">
    <el-aside class="sidebar" width="248px">
      <div class="brand">
        <span class="brand-mark">F</span>
        <div>
          <strong>Fastener AI</strong>
          <small>外销助手</small>
        </div>
      </div>

      <el-menu :default-active="route.path" router class="nav-menu">
        <el-menu-item v-for="item in visibleMenu" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">MVP 骨架 · v0.9</div>
    </el-aside>

    <el-container>
      <el-header class="topbar" height="76px">
        <div class="topbar-title">
          <span class="eyebrow">紧固件出口业务</span>
          <h1>{{ pageTitle }}</h1>
        </div>

        <div class="topbar-right">
          <el-tag class="tenant-tag" effect="plain" round>{{ auth.user?.tenant.name ?? '未知企业' }}</el-tag>
          <el-dropdown trigger="click" @command="handleCommand">
            <button class="user-button" type="button">
              <el-avatar :size="34">{{ initials }}</el-avatar>
              <span class="user-meta">
                <strong>{{ displayName }}</strong>
                <small>{{ roleLabel }}</small>
              </span>
              <el-icon><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
}

.sidebar {
  display: flex;
  flex-direction: column;
  background: #0f1f3d;
  color: #dbe5f5;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 22px 20px 18px;
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border-radius: 12px;
  background: linear-gradient(135deg, #3b82f6, #06b6d4);
  color: #fff;
  font-size: 20px;
  font-weight: 800;
}

.brand strong {
  display: block;
  color: #fff;
  font-size: 16px;
  letter-spacing: 0.02em;
}

.brand small {
  color: #8fa6c9;
  font-size: 12px;
}

.nav-menu {
  flex: 1;
  border-right: 0;
  background: transparent;
}

.nav-menu :deep(.el-menu-item) {
  margin: 4px 12px;
  border-radius: 10px;
  color: #b9c8e0;
}

.nav-menu :deep(.el-menu-item:hover) {
  background: rgba(59, 130, 246, 0.16);
  color: #fff;
}

.nav-menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.9), rgba(6, 182, 212, 0.75));
  color: #fff;
  font-weight: 600;
}

.sidebar-footer {
  padding: 18px 20px;
  color: #7288a8;
  font-size: 12px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid #e5e9f2;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
}

.topbar-title {
  min-width: 0;
}

.eyebrow {
  color: #8a97ad;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.topbar h1 {
  margin: 2px 0 0;
  overflow: hidden;
  color: #14213d;
  font-size: 22px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-button {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  cursor: pointer;
}

.user-button:hover {
  border-color: #dbe3f0;
  background: #f7f9fc;
}

.user-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.2;
}

.user-meta strong {
  color: #1b2a4a;
  font-size: 13px;
}

.user-meta small {
  color: #8a97ad;
  font-size: 11px;
}

.content {
  padding: 24px;
}

@media (max-width: 1024px) {
  .tenant-tag,
  .user-meta {
    display: none;
  }
}
</style>
