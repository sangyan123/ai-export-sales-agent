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
  Expand,
  Files,
  Fold,
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

const COLLAPSE_STORAGE_KEY = 'fastener-ai:sidebar-collapsed'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const menuRef = ref<MenuInstance>()
const collapsed = ref(localStorage.getItem(COLLAPSE_STORAGE_KEY) === '1')

watch(collapsed, (value) => {
  localStorage.setItem(COLLAPSE_STORAGE_KEY, value ? '1' : '0')
})

function toggleCollapsed(): void {
  collapsed.value = !collapsed.value
}

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
  if (!collapsed.value && activeGroupKey.value) {
    menuRef.value?.open(activeGroupKey.value)
  }
}

watch([activeGroupKey, collapsed], ensureActiveGroupOpen)
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
    <el-aside class="sidebar" :class="{ collapsed }" :width="collapsed ? '64px' : '248px'">
      <div class="brand">
        <span class="brand-mark">F</span>
        <div class="brand-text">
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
        :collapse="collapsed"
        :collapse-transition="true"
      >
        <el-menu-item
          v-for="item in visibleTopItems"
          :key="item.path"
          :index="item.path"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.label }}</template>
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
            <template #title>{{ item.label }}</template>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>

      <div class="sidebar-footer">
        <span class="version-pill">v0.9</span>
        <span v-if="!collapsed">MVP 试点版</span>
      </div>
    </el-aside>

    <el-container>
      <el-header class="topbar" height="68px">
        <div class="topbar-left">
          <el-tooltip
            :content="collapsed ? '展开菜单' : '收起菜单'"
            placement="bottom"
            :show-after="300"
          >
            <button
              class="collapse-button"
              type="button"
              :aria-label="collapsed ? '展开侧边菜单' : '收起侧边菜单'"
              @click="toggleCollapsed"
            >
              <el-icon :size="18">
                <Expand v-if="collapsed" />
                <Fold v-else />
              </el-icon>
            </button>
          </el-tooltip>
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
  background: #f5f6fa;
}

.sidebar {
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-right: 1px solid #eceef4;
  color: #1e2433;
  transition: width 0.22s ease;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 22px 20px 18px;
  border-bottom: 1px solid #f1f3f8;
  white-space: nowrap;
  overflow: hidden;
}

.sidebar.collapsed .brand {
  justify-content: center;
  padding: 20px 0 16px;
}

.sidebar.collapsed .brand-text {
  display: none;
}

.brand-mark {
  display: grid;
  width: 40px;
  height: 40px;
  flex: none;
  place-items: center;
  border-radius: 12px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  font-size: 20px;
  font-weight: 800;
  box-shadow: 0 4px 14px rgba(99, 102, 241, 0.3);
}

.brand-text strong {
  display: block;
  color: #1e2433;
  font-size: 16px;
  letter-spacing: 0.02em;
}

.brand-text small {
  color: #9aa1b5;
  font-size: 12px;
}

.nav-menu {
  --el-menu-bg-color: transparent;
  --el-menu-text-color: #5b6377;
  --el-menu-hover-bg-color: #f5f6fa;
  --el-menu-active-color: #4f46e5;

  flex: 1;
  padding: 10px 12px;
  border-right: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

.sidebar.collapsed .nav-menu {
  padding: 10px 8px;
}

.nav-menu:not(.el-menu--collapse) {
  width: 100%;
}

.nav-menu .el-menu-item,
.nav-menu :deep(.el-sub-menu__title) {
  height: 44px;
  margin: 2px 0;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 44px;
  transition: background 0.18s ease, color 0.18s ease;
}

.sidebar.collapsed .nav-menu .el-menu-item,
.sidebar.collapsed .nav-menu :deep(.el-sub-menu__title) {
  width: 48px;
  min-width: 48px;
  height: 44px;
  margin: 3px auto;
  padding: 0 !important;
  justify-content: center;
}

/* 收起态：EP tooltip 触发器默认 padding 0 20px，会把图标挤偏，清零并居中 */
.sidebar.collapsed .nav-menu :deep(.el-menu-item .el-menu-tooltip__trigger) {
  width: 100%;
  justify-content: center;
  padding: 0 !important;
}

/* 收起态：图标强制水平居中 */
.sidebar.collapsed .nav-menu :deep(.el-menu-item .el-icon),
.sidebar.collapsed .nav-menu :deep(.el-sub-menu__title > .el-icon) {
  margin: 0 auto;
}

.nav-menu .el-menu-item:hover,
.nav-menu :deep(.el-sub-menu__title:hover) {
  background: #f5f6fa;
  color: #1e2433;
}

.nav-menu .el-menu-item.is-active {
  position: relative;
  background: #eef0ff;
  color: #4f46e5;
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
  background: #4f46e5;
}

.sidebar.collapsed .nav-menu .el-menu-item.is-active::before {
  top: 15%;
  bottom: 15%;
}

.nav-menu :deep(.el-sub-menu.is-opened > .el-sub-menu__title) {
  color: #1e2433;
  font-weight: 600;
}

.nav-menu :deep(.el-sub-menu .el-menu-item) {
  padding-left: 44px !important;
  font-size: 13px;
}

.sidebar-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 16px 12px;
  border-top: 1px solid #f1f3f8;
  color: #9aa1b5;
  font-size: 12px;
  white-space: nowrap;
}

.version-pill {
  padding: 2px 10px;
  border-radius: 999px;
  background: #eef0ff;
  color: #4f46e5;
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
  border-bottom: 1px solid #eceef4;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(10px);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.collapse-button {
  display: grid;
  width: 34px;
  height: 34px;
  flex: none;
  place-items: center;
  border: 1px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: #5b6377;
  cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease;
}

.collapse-button:hover {
  border-color: #e3e6ee;
  background: #f5f6fa;
  color: #4f46e5;
}

.topbar-left h1 {
  margin: 0;
  overflow: hidden;
  color: #1e2433;
  font-size: 18px;
  letter-spacing: 0.01em;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  border: 1px solid #e3e6ee;
  border-radius: 999px;
  background: #ffffff;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease;
}

.user-button:hover {
  border-color: #c9cef0;
  background: #f6f7ff;
}

.user-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.2;
}

.user-meta strong {
  color: #1e2433;
  font-size: 13px;
}

.user-meta small {
  color: #9aa1b5;
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
