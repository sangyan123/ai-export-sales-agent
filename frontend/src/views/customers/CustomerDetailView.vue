<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Edit } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchCustomer } from '@/api/customers'
import { ApiError } from '@/api/http'
import { CUSTOMER_STATUS_LABELS, CUSTOMER_STATUS_TAG } from '@/constants/catalog'
import { useAuthStore } from '@/stores/auth'
import type { Customer, CustomerStatus } from '@/types/customer'
import { formatDateTime } from '@/utils/format'

import ContactPanel from './components/ContactPanel.vue'
import CustomerFollowupPanel from './components/CustomerFollowupPanel.vue'
import CustomerFormDialog from './components/CustomerFormDialog.vue'
import CustomerInquiryPanel from './components/CustomerInquiryPanel.vue'
import CustomerNotePanel from './components/CustomerNotePanel.vue'
import PriceOverridePanel from './components/PriceOverridePanel.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const customer = ref<Customer | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const editVisible = ref(false)
const activeTab = ref('contacts')

const customerId = computed(() => String(route.params.id ?? ''))
const canEdit = computed(() => auth.hasPermission('customer:update'))

async function load(id: string): Promise<void> {
  loading.value = true
  errorMessage.value = ''
  try {
    customer.value = await fetchCustomer(id)
  } catch (error) {
    customer.value = null
    errorMessage.value = error instanceof ApiError ? error.message : '加载客户资料失败'
    if (!(error instanceof ApiError) || error.status !== 404) {
      ElMessage.error(errorMessage.value)
    }
  } finally {
    loading.value = false
  }
}

function goBack(): void {
  void router.push({ name: 'customers' })
}

function handleSaved(saved: Customer): void {
  customer.value = saved
}

watch(
  customerId,
  (id) => {
    if (id) {
      void load(id)
    }
  },
  { immediate: true },
)
</script>

<template>
  <section v-loading="loading" class="detail-page">
    <el-result
      v-if="errorMessage && !customer"
      icon="warning"
      title="无法打开客户资料"
      :sub-title="errorMessage"
    >
      <template #extra>
        <el-button type="primary" @click="goBack">返回客户列表</el-button>
      </template>
    </el-result>

    <template v-else-if="customer">
      <el-card shadow="never" class="head-card">
        <div class="detail-head">
          <div class="head-left">
            <el-button text :icon="ArrowLeft" @click="goBack">返回列表</el-button>
            <div>
              <div class="title-row">
                <h2>{{ customer.company_name }}</h2>
                <el-tag :type="CUSTOMER_STATUS_TAG[customer.status as CustomerStatus]" effect="plain">
                  {{ CUSTOMER_STATUS_LABELS[customer.status as CustomerStatus] }}
                </el-tag>
              </div>
              <p class="subtitle">
                {{ customer.country_code || '未填写国家' }} · 更新于
                {{ formatDateTime(customer.updated_at) }}
              </p>
            </div>
          </div>
          <el-button v-if="canEdit" :icon="Edit" @click="editVisible = true">编辑资料</el-button>
        </div>

        <el-descriptions :column="3" class="profile" border>
          <el-descriptions-item label="国家/地区">
            {{ customer.country_code || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="来源">{{ customer.source || '—' }}</el-descriptions-item>
          <el-descriptions-item label="网站">
            <a
              v-if="customer.website"
              :href="customer.website"
              target="_blank"
              rel="noreferrer"
              class="website-link"
            >
              {{ customer.website }}
            </a>
            <span v-else class="muted">—</span>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatDateTime(customer.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="更新时间">
            {{ formatDateTime(customer.updated_at) }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card shadow="never" class="body-card">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="联系人" name="contacts">
            <ContactPanel :customer-id="customer.id" />
          </el-tab-pane>
          <el-tab-pane label="备注" name="notes">
            <CustomerNotePanel :customer-id="customer.id" />
          </el-tab-pane>
          <el-tab-pane label="专属价" name="pricing">
            <PriceOverridePanel :customer-id="customer.id" />
          </el-tab-pane>
          <el-tab-pane label="关联询盘" name="inquiries">
            <CustomerInquiryPanel :customer-id="customer.id" />
          </el-tab-pane>
          <el-tab-pane label="跟进任务" name="followups">
            <CustomerFollowupPanel :customer-id="customer.id" />
          </el-tab-pane>
        </el-tabs>
      </el-card>

      <CustomerFormDialog v-model="editVisible" :customer="customer" @saved="handleSaved" />
    </template>
  </section>
</template>

<style scoped>
.detail-page {
  display: grid;
  gap: 16px;
}

.head-card,
.body-card {
  border-radius: 16px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
}

.head-left {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title-row h2 {
  margin: 0;
  color: #14213d;
  font-size: 22px;
}

.subtitle {
  margin: 6px 0 0;
  color: #8a97ad;
  font-size: 12px;
}

.profile {
  margin-top: 4px;
}

.website-link {
  color: #2563eb;
}

.website-link:hover {
  text-decoration: underline;
}

.muted {
  color: #9aa6b8;
}
</style>
