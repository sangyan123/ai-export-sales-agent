<script setup lang="ts">
import { computed, markRaw, onMounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Box,
  Calendar,
  ChatDotRound,
  Document,
  Lock,
  TrendCharts,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'

import { getEnvelope } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

interface StatCard {
  key: string
  label: string
  description: string
  path: string
  permission: string
  url: string
  icon: Component
  accent: string
  count: number | null
  available: boolean
  failed: boolean
}

const ROLE_LABELS: Record<string, string> = {
  OWNER: '企业所有者',
  TENANT_ADMIN: '企业管理员',
  SALES_MANAGER: '销售主管',
  SALES_REP: '业务员',
  APPROVER: '审批人',
  VIEWER: '只读成员',
}

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const cards = reactive<StatCard[]>([
  {
    key: 'inquiries',
    label: '询盘',
    description: '待解析、待匹配与待报价询盘',
    path: '/inquiries',
    permission: 'inquiry:read',
    url: '/inquiries',
    icon: markRaw(ChatDotRound),
    accent: '#2563eb',
    count: null,
    available: true,
    failed: false,
  },
  {
    key: 'quotes',
    label: '报价',
    description: '报价草案、审批队列与历史版本',
    path: '/quotes',
    permission: 'quote:read',
    url: '/quotes',
    icon: markRaw(Document),
    accent: '#0d9488',
    count: null,
    available: true,
    failed: false,
  },
  {
    key: 'customers',
    label: '客户',
    description: '客户档案、联系人与专属价',
    path: '/customers',
    permission: 'customer:read',
    url: '/customers',
    icon: markRaw(TrendCharts),
    accent: '#7c3aed',
    count: null,
    available: true,
    failed: false,
  },
  {
    key: 'followups',
    label: '跟进任务',
    description: '待办、到期提醒与完成记录',
    path: '/followups',
    permission: 'followup:read',
    url: '/followups',
    icon: markRaw(Calendar),
    accent: '#ea580c',
    count: null,
    available: true,
    failed: false,
  },
  {
    key: 'products',
    label: '产品',
    description: '产品目录、规格与价格表',
    path: '/products',
    permission: 'product:read',
    url: '/products',
    icon: markRaw(Box),
    accent: '#0284c7',
    count: null,
    available: true,
    failed: false,
  },
])

const deniedPermission = computed(() =>
  typeof route.query.denied === 'string' ? route.query.denied : '',
)
const displayName = computed(() => auth.user?.display_name ?? '用户')
const tenantName = computed(() => auth.user?.tenant.name ?? '当前企业')
const roleLabel = computed(() => ROLE_LABELS[auth.user?.role ?? ''] ?? auth.user?.role ?? '')
const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 12) {
    return '早上好'
  }
  if (hour < 18) {
    return '下午好'
  }
  return '晚上好'
})

async function loadCounts(): Promise<void> {
  await Promise.all(
    cards.map(async (card) => {
      if (!auth.hasPermission(card.permission)) {
        card.available = false
        return
      }
      try {
        const envelope = await getEnvelope<unknown[]>(card.url, {
          params: { page: 1, page_size: 1 },
        })
        card.count = envelope.meta.total ?? 0
      } catch {
        card.failed = true
      }
    }),
  )
}

function openCard(card: StatCard): void {
  if (card.available) {
    void router.push(card.path)
  }
}

onMounted(loadCounts)
</script>

<template>
  <div class="dashboard">
    <el-alert
      v-if="deniedPermission"
      class="denied-alert"
      type="warning"
      show-icon
      :closable="false"
      title="当前角色无权访问该页面"
      :description="`缺少权限：${deniedPermission}`"
    />

    <section class="welcome-card">
      <div>
        <p class="eyebrow">{{ tenantName }} · {{ roleLabel }}</p>
        <h2>{{ greeting }}，{{ displayName }}</h2>
        <p class="welcome-copy">
          从询盘解析到报价审批、邮件草案与客户跟进，核心流程已接入后端 API。
        </p>
      </div>
      <div class="welcome-badge">
        <el-icon :size="30"><Lock /></el-icon>
        <span>多租户隔离</span>
      </div>
    </section>

    <section class="stat-grid">
      <article
        v-for="card in cards"
        :key="card.key"
        class="stat-card"
        :class="{ disabled: !card.available }"
        @click="openCard(card)"
      >
        <div class="stat-icon" :style="{ background: `${card.accent}14`, color: card.accent }">
          <el-icon :size="22"><component :is="card.icon" /></el-icon>
        </div>
        <div class="stat-body">
          <span class="stat-label">{{ card.label }}</span>
          <strong v-if="card.failed" class="stat-error">加载失败</strong>
          <strong v-else-if="card.count !== null">{{ card.count }}</strong>
          <strong v-else-if="!card.available" class="stat-muted">无权限</strong>
          <strong v-else class="stat-muted">—</strong>
          <p>{{ card.description }}</p>
        </div>
      </article>
    </section>

    <section class="lower-grid">
      <el-card shadow="never" class="panel">
        <template #header>
          <div class="panel-header">
            <span>推荐处理顺序</span>
            <el-tag size="small" effect="plain">MVP 主流程</el-tag>
          </div>
        </template>
        <ol class="flow-list">
          <li><span>1</span>录入或导入询盘，上传原始邮件与附件</li>
          <li><span>2</span>运行 AI 解析，确认缺失字段与关键规格</li>
          <li><span>3</span>生成产品匹配候选，检查冲突项</li>
          <li><span>4</span>创建报价并提交审批，导出 PDF / XLSX</li>
          <li><span>5</span>生成邮件草案，审批后复制发送</li>
          <li><span>6</span>创建客户跟进任务并按时回访</li>
        </ol>
      </el-card>

      <el-card shadow="never" class="panel">
        <template #header>
          <div class="panel-header">
            <span>当前登录信息</span>
            <el-tag size="small" type="success" effect="plain">已认证</el-tag>
          </div>
        </template>
        <dl class="account-list">
          <div><dt>企业</dt><dd>{{ tenantName }}</dd></div>
          <div><dt>角色</dt><dd>{{ roleLabel }}</dd></div>
          <div><dt>邮箱</dt><dd>{{ auth.user?.email }}</dd></div>
          <div><dt>权限数量</dt><dd>{{ auth.user?.permissions.length ?? 0 }}</dd></div>
        </dl>
      </el-card>
    </section>
  </div>
</template>

<style scoped>
.dashboard {
  display: grid;
  gap: 20px;
}

.denied-alert {
  margin-bottom: 0;
}

.welcome-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 30px 34px;
  border-radius: 20px;
  background:
    radial-gradient(circle at 90% 20%, rgba(6, 182, 212, 0.25), transparent 32%),
    linear-gradient(120deg, #12284f, #173a6b);
  color: #fff;
}

.eyebrow {
  margin: 0 0 8px;
  color: #8fd8f5;
  font-size: 12px;
  letter-spacing: 0.08em;
}

.welcome-card h2 {
  margin: 0 0 10px;
  font-size: 28px;
}

.welcome-copy {
  margin: 0;
  color: #b6c8e5;
  font-size: 14px;
}

.welcome-badge {
  display: grid;
  gap: 8px;
  padding: 18px 22px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.06);
  color: #d8f3ff;
  font-size: 12px;
  text-align: center;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 16px;
}

.stat-card {
  display: flex;
  gap: 14px;
  padding: 20px;
  border: 1px solid #e5e9f2;
  border-radius: 16px;
  background: #fff;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 30px rgba(20, 33, 61, 0.08);
}

.stat-card.disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.stat-icon {
  display: grid;
  width: 44px;
  height: 44px;
  flex: none;
  place-items: center;
  border-radius: 12px;
}

.stat-body {
  display: grid;
  gap: 4px;
}

.stat-label {
  color: #7b879c;
  font-size: 12px;
}

.stat-body strong {
  color: #14213d;
  font-size: 26px;
  line-height: 1.1;
}

.stat-body strong.stat-muted,
.stat-body strong.stat-error {
  font-size: 14px;
  font-weight: 600;
}

.stat-error {
  color: #dc2626;
}

.stat-muted {
  color: #9aa6b8;
}

.stat-body p {
  margin: 0;
  color: #9aa6b8;
  font-size: 12px;
  line-height: 1.6;
}

.lower-grid {
  display: grid;
  grid-template-columns: 1.35fr 0.65fr;
  gap: 16px;
}

.panel {
  border-radius: 16px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #1b2a4a;
  font-weight: 600;
}

.flow-list {
  display: grid;
  gap: 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.flow-list li {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #4c5b74;
  font-size: 13px;
}

.flow-list span {
  display: grid;
  width: 24px;
  height: 24px;
  flex: none;
  place-items: center;
  border-radius: 50%;
  background: #eff6ff;
  color: #2563eb;
  font-size: 11px;
  font-weight: 700;
}

.account-list {
  display: grid;
  gap: 14px;
  margin: 0;
}

.account-list div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 12px;
  border-bottom: 1px dashed #e8edf5;
}

.account-list div:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.account-list dt {
  color: #8a97ad;
  font-size: 12px;
}

.account-list dd {
  margin: 0;
  color: #1b2a4a;
  font-size: 13px;
  font-weight: 600;
  text-align: right;
  word-break: break-all;
}

@media (max-width: 1100px) {
  .lower-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .welcome-card {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
