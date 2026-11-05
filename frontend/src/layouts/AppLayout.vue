<script setup lang="ts">
import { computed, onMounted, ref, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { MenuInstance } from 'element-plus'
import {
  ArrowDown,
  Box,
  Calendar,
  ChatDotRound,
  Collection,
  Document,
  Files,
  MagicStick,
  Odometer,
  PriceTag,
  Setting,
  Tickets,
  User,
  UserFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { MEMBER_ROLE_LABELS } from '@/constants/member'
import { useAuthStore } from '@/stores/auth'
import type { MemberRole } from '@/types/member'

interface MenuItem {
  path: string
  label: string
  icon: Component
  permission?: string
}

interface MenuGroup {
  key: string
  label: string
  icon: Component
  items: MenuItem[]
}

/** 顶级（不分组的）菜单项 */
const topItems: MenuItem[] = [
  { path: '/', label: '工作台', icon: Odometer },
  { path: '/ai', label: 'AI 工作台', icon: MagicStick, permission: 'workflow:read' },
]

/** 分组菜单 */
const menuGroups: MenuGroup[] = [
  {
    key: 'business',
    label: '业务流程',
    icon: Files,
    items: [
      { path: '/inquiries', label: '询盘管理', icon: ChatDotRound, permission: 'inquiry:read' },
      { path: '/quotes', label: '报价中心', icon: Document, permission: 'quote:read' },
      { path: '/followups', label: '跟进管理', icon: Calendar, permission: 'followup:read' },
    ],
  },
  {
    key: 'data',
    label: '客户与产品',
    icon: Collection,
    items: [
      { path: '/products', label: '产品中心', icon: Box, permission: 'product:read' },
      { path: '/customers', label: '客户管理', icon: User, permission: 'customer:read' },
    ],
  },
  {
    key: 'settings',
    label: '企业管理',
    icon: Setting,
    items: [
      { path: '/settings', label: '企业资料', icon: Setting, permission: 'tenant:read' },
      { path: '/settings/members', label: '成员管理', icon: UserFilled, permission: 'member:read' },
      { path: '/settings/pricing', label: '价格策略', icon: PriceTag, permission: 'pricing:read' },
      { path: '/audit-logs', label: '审计日志', icon: Tickets, permission: 'audit:read' },
    ],
  },
]

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const menuRef = ref<MenuInstance>()

const visibleTopItems = computed(() =>
  topItems.filter((item) => !item.permission || auth.hasPermission(item.permission)),
)
const visibleGroups = computed(() =>
  menuGroups
    .map((group) => ({
      ...group,
      items: group.items.filter(
        (item) => !item.permission || auth.hasPermission(item.permission),
      ),
    }))
    .filter((group) => group.items.length > 0),
)
const pageTitle = computed(() =>
  typeof route.meta.title === 'string' ? route.meta.title : '工作台',
)
const activeMenu = computed(() =>
  typeof route.meta.activeMenu === 'string' ? route.meta.activeMenu : route.path,
)
const activeGroupKey = computed(
  () =>
    visibleGroups.value.find((group) =>
      group.items.some((item) => item.path === activeMenu.value),
    )?.key ?? '',
)
const displayName = computed(() => auth.user?.display_name ?? '未登录')
const roleLabel = computed(() => {
  const role = auth.user?.role ?? ''
  return MEMBER_ROLE_LABELS[role as MemberRole] ?? role
})
const initials = computed(() => displayName.value.trim().charAt(0).toUpperCase() || 'U')

function ensureActiveGroupOpen(): void {
  if (activeGroupKey.value) {
    menuRef.value?.open(activeGroupKey.value)
  }
}

watch(activeGroupKey, ensureActiveGroupOpen)
onMounted(ensureActiveGroupOpen)

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

      <el-menu
        ref="menuRef"
        :default-active="activeMenu"
        router
        class="nav-menu"
        unique-opened
      >
        <el-menu-item
          v-for="item in visibleTopItems"
          :key="item.path"
          :index="item.path"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>

        <el-sub-menu
          v-for="group in visibleGroups"
          :key="group.key"
          :index="group.key"
        >
          <template #title>
            <el-icon><component :is="group.icon" /></el-icon>
            <span>{{ group.label }}</span>
          </template>
          <el-menu-item
            v-for="item in group.items"
            :key="item.path"
            :index="item.path"
          >
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>

      <div class="sidebar-footer">
        <span class="version-pill">v0.9</span>
        <span>MVP 试点版</span>
      </div>
    </el-aside>

    <el-container>
      <el-header class="topbar" height="68px">
        <div class="topbar-title">
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
  background: linear-gradient(180deg, #10233f 0%, #0b1730 100%);
  color: #dbe5f5;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 22px 20px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  flex: none;
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
  --el-menu-bg-color: transparent;
  --el-menu-text-color: #a7b6d3;
  --el-menu-hover-bg-color: rgba(255, 255, 255, 0.06);
  --el-menu-active-color: #ffffff;

  flex: 1;
  padding: 10px 12px;
  border-right: 0;
  overflow-y: auto;
}

.nav-menu .el-menu-item,
.nav-menu :deep(.el-sub-menu__title) {
  height: 44px;
  margin: 2px 0;
  border-radius: 10px;
  font-size: 13.5px;
  line-height: 44px;
  transition: background 0.18s ease, color 0.18s ease;
}

.nav-menu .el-menu-item:hover,
.nav-menu :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.07);
  color: #e8f0ff;
}

.nav-menu .el-menu-item.is-active {
  position: relative;
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.32), rgba(59, 130, 246, 0.14));
  color: #fff;
  font-weight: 600;
}

.nav-menu .el-menu-item.is-active::before {
  content: '';
  position: absolute;
  top: 22%;
  bottom: 22%;
  left: 0;
  width: 3px;
  border-radius: 3px;
  background: #60a5fa;
}

.nav-menu :deep(.el-sub-menu.is-opened > .el-sub-menu__title) {
  color: #dce9ff;
  font-weight: 600;
}

.nav-menu :deep(.el-sub-menu .el-menu-item) {
  padding-left: 44px !important;
  font-size: 13px;
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
  color: #7c8fb0;
  font-size: 12px;
}

.version-pill {
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(96, 165, 250, 0.16);
  color: #9cc4fd;
  font-weight: 600;
}

.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 24px;
  border-bottom: 1px solid #e8edf5;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
}

.topbar-title h1 {
  margin: 0;
  color: #14213d;
  font-size: 18px;
  letter-spacing: 0.01em;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.tenant-tag {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-button {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px 6px 6px;
  border: 1px solid #dbe3f0;
  border-radius: 999px;
  background: #f7f9fc;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease;
}

.user-button:hover {
  border-color: #b8c8e4;
  background: #f0f5fd;
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
