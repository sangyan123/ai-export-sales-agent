import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    title?: string
    permission?: string
    activeMenu?: string
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '工作台' },
      },
      {
        path: 'inquiries',
        name: 'inquiries',
        component: () => import('@/views/inquiries/InquiryListView.vue'),
        meta: { title: '询盘管理', permission: 'inquiry:read' },
      },
      {
        path: 'inquiries/:id',
        name: 'inquiry-detail',
        component: () => import('@/views/inquiries/InquiryDetailView.vue'),
        meta: { title: '询盘详情', permission: 'inquiry:read', activeMenu: '/inquiries' },
      },
      {
        path: 'quotes',
        name: 'quotes',
        component: () => import('@/views/quotes/QuoteListView.vue'),
        meta: { title: '报价中心', permission: 'quote:read' },
      },
      {
        path: 'quotes/:id',
        name: 'quote-detail',
        component: () => import('@/views/quotes/QuoteDetailView.vue'),
        meta: { title: '报价详情', permission: 'quote:read', activeMenu: '/quotes' },
      },
      {
        path: 'products',
        name: 'products',
        component: () => import('@/views/products/ProductListView.vue'),
        meta: { title: '产品中心', permission: 'product:read' },
      },
      {
        path: 'customers',
        name: 'customers',
        component: () => import('@/views/customers/CustomerListView.vue'),
        meta: { title: '客户管理', permission: 'customer:read' },
      },
      {
        path: 'customers/:id',
        name: 'customer-detail',
        component: () => import('@/views/customers/CustomerDetailView.vue'),
        meta: { title: '客户详情', permission: 'customer:read', activeMenu: '/customers' },
      },
      {
        path: 'followups',
        name: 'followups',
        component: () => import('@/views/followups/FollowupListView.vue'),
        meta: { title: '跟进管理', permission: 'followup:read' },
      },
      {
        path: 'ai',
        name: 'ai',
        component: () => import('@/views/ai/AiWorkspaceView.vue'),
        meta: { title: 'AI 工作台', permission: 'workflow:read' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/settings/SettingsView.vue'),
        meta: { title: '企业设置', permission: 'tenant:read' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    if (to.name === 'login' && auth.isAuthenticated) {
      return { name: 'dashboard' }
    }
    return true
  }

  if (!auth.isAuthenticated) {
    return {
      name: 'login',
      query: { redirect: to.fullPath },
    }
  }

  const permission = to.meta.permission
  if (permission && !auth.hasPermission(permission)) {
    return {
      name: 'dashboard',
      query: { denied: permission },
    }
  }

  return true
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : '工作台'
  document.title = `${title} · 紧固件 AI 外销助手`
})
