<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { createContact, fetchContacts, updateContact } from '@/api/customers'
import { ApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import type { Contact, ContactPayload } from '@/types/customer'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ customerId: string }>()

const auth = useAuthStore()
const contacts = ref<Contact[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const saving = ref(false)
const editing = ref<Contact | null>(null)
const formRef = ref<FormInstance>()

const canEdit = computed(() => auth.hasPermission('customer:update'))

const form = reactive({
  name: '',
  email: '',
  phone: '',
  language: '',
  job_title: '',
  is_primary: false,
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入联系人姓名', trigger: 'blur' }],
  email: [
    {
      pattern: /^[^@\s]+@[^@\s]+\.[^@\s]+$/,
      message: '请输入有效的邮箱地址',
      trigger: 'blur',
    },
  ],
  language: [
    { pattern: /^[a-z]{2}(-[a-z]{2})?$/, message: "语言格式如 'en' 或 'en-us'", trigger: 'blur' },
  ],
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const envelope = await fetchContacts(props.customerId, { page_size: 100 })
    contacts.value = envelope.data
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '加载联系人失败')
  } finally {
    loading.value = false
  }
}

async function openDialog(contact?: Contact): Promise<void> {
  editing.value = contact ?? null
  form.name = contact?.name ?? ''
  form.email = contact?.email ?? ''
  form.phone = contact?.phone ?? ''
  form.language = contact?.language ?? ''
  form.job_title = contact?.job_title ?? ''
  form.is_primary = contact?.is_primary ?? contacts.value.length === 0
  dialogVisible.value = true
  await nextTick()
  formRef.value?.clearValidate()
}

async function submit(): Promise<void> {
  if (!formRef.value) {
    return
  }
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }

  const payload: ContactPayload = {
    name: form.name.trim(),
    email: form.email.trim().toLowerCase() || null,
    phone: form.phone.trim() || null,
    language: form.language.trim().toLowerCase() || null,
    job_title: form.job_title.trim() || null,
    is_primary: form.is_primary,
  }

  saving.value = true
  try {
    if (editing.value) {
      await updateContact(props.customerId, editing.value.id, payload)
      ElMessage.success('联系人已更新')
    } else {
      await createContact(props.customerId, payload)
      ElMessage.success('联系人已添加')
    }
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof ApiError ? error.message : '保存联系人失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="panel">
    <div class="panel-toolbar">
      <span class="hint">主联系人会用于报价与邮件默认收件人，每个客户只能有一个。</span>
      <el-button v-if="canEdit" type="primary" :icon="Plus" size="small" @click="openDialog()">
        添加联系人
      </el-button>
    </div>

    <el-table v-loading="loading" :data="contacts" row-key="id">
      <el-table-column label="姓名" min-width="150">
        <template #default="{ row }">
          <span class="contact-name">{{ row.name }}</span>
          <el-tag v-if="row.is_primary" size="small" type="success" effect="plain" class="primary-tag">
            主联系人
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="job_title" label="职位" min-width="130">
        <template #default="{ row }">{{ row.job_title || '—' }}</template>
      </el-table-column>
      <el-table-column label="邮箱" min-width="200">
        <template #default="{ row }">
          <a v-if="row.email" :href="`mailto:${row.email}`" class="mail-link">{{ row.email }}</a>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="phone" label="电话" min-width="140">
        <template #default="{ row }">{{ row.phone || '—' }}</template>
      </el-table-column>
      <el-table-column prop="language" label="语言" width="90" align="center">
        <template #default="{ row }">{{ row.language || '—' }}</template>
      </el-table-column>
      <el-table-column label="更新时间" width="180">
        <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column v-if="canEdit" label="操作" width="90" align="center">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDialog(row)">编辑</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="暂无联系人，添加后可用于报价与邮件" />
      </template>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑联系人' : '添加联系人'"
      width="520px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="姓名" prop="name">
          <el-input v-model="form.name" maxlength="160" placeholder="联系人姓名" />
        </el-form-item>
        <el-form-item label="职位" prop="job_title">
          <el-input v-model="form.job_title" maxlength="120" placeholder="Purchasing Manager" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" maxlength="320" placeholder="buyer@example.com" />
        </el-form-item>
        <el-form-item label="电话" prop="phone">
          <el-input v-model="form.phone" maxlength="40" placeholder="+49 123 456789" />
        </el-form-item>
        <el-form-item label="语言" prop="language">
          <el-input v-model="form.language" maxlength="16" placeholder="en / de / en-us" style="width: 180px" />
        </el-form-item>
        <el-form-item label="主联系人">
          <el-switch v-model="form.is_primary" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.panel {
  display: grid;
  gap: 12px;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.hint {
  color: #8a97ad;
  font-size: 12px;
}

.contact-name {
  font-weight: 600;
  color: #1b2a4a;
}

.primary-tag {
  margin-left: 8px;
}

.mail-link {
  color: #4f46e5;
}

.muted {
  color: #9aa6b8;
}
</style>
