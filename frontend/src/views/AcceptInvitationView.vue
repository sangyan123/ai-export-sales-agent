<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormItemRule, FormRules } from 'element-plus'

import { acceptInvitation } from '@/api/auth'
import { ApiError } from '@/api/http'
import { clearTokens, setTokens } from '@/api/tokens'
import { MEMBER_ERROR_MESSAGES } from '@/constants/member'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const token = typeof route.query.token === 'string' ? route.query.token : ''
const formRef = ref<FormInstance>()
const loading = ref(false)
const errorMessage = ref('')

const form = reactive({
  display_name: '',
  password: '',
  confirm_password: '',
})

const validatePassword: FormItemRule['validator'] = (_rule, value, callback) => {
  const password = String(value ?? '')
  if (!password) {
    callback(new Error('请输入密码'))
    return
  }
  if (password.length < 8) {
    callback(new Error('密码至少 8 位'))
    return
  }
  if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
    callback(new Error('密码需同时包含字母和数字'))
    return
  }
  callback()
}

const validateConfirm: FormItemRule['validator'] = (_rule, value, callback) => {
  if (!value) {
    callback(new Error('请再次输入密码'))
    return
  }
  if (value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
    return
  }
  callback()
}

const rules: FormRules = {
  display_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  password: [{ required: true, validator: validatePassword, trigger: 'blur' }],
  confirm_password: [{ required: true, validator: validateConfirm, trigger: 'blur' }],
}

function backToLogin(): void {
  void router.replace({ name: 'login' })
}

async function submit(): Promise<void> {
  if (!token || !formRef.value) {
    return
  }
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await acceptInvitation({
      token,
      display_name: form.display_name.trim(),
      password: form.password,
    })
    setTokens(result.tokens)
    try {
      await auth.loadCurrentUser()
    } catch {
      clearTokens()
      ElMessage.warning('账号已启用，但自动登录失败，请手动登录')
      backToLogin()
      return
    }
    ElMessage.success('邀请已接受，欢迎加入')
    await router.replace('/')
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError
        ? (MEMBER_ERROR_MESSAGES[error.code] ?? error.message)
        : '接受邀请失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="accept-page">
    <div class="accept-card">
      <template v-if="!token">
        <p class="kicker">MEMBER INVITATION</p>
        <h1>邀请链接无效</h1>
        <p class="subtitle">链接缺少邀请令牌，请联系企业管理员重新发送邀请。</p>
        <el-button class="submit-button" type="primary" @click="backToLogin">
          返回登录
        </el-button>
      </template>
      <template v-else>
        <p class="kicker">MEMBER INVITATION</p>
        <h1>加入企业工作台</h1>
        <p class="subtitle">
          设置姓名和登录密码后即可开始使用。密码至少 8 位，并同时包含字母和数字。
        </p>
        <el-alert
          v-if="errorMessage"
          class="notice"
          :title="errorMessage"
          type="error"
          :closable="false"
          show-icon
        />
        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
          @submit.prevent="submit"
        >
          <el-form-item label="姓名" prop="display_name">
            <el-input
              v-model="form.display_name"
              :prefix-icon="User"
              placeholder="你的姓名或称呼"
              maxlength="120"
              autocomplete="name"
            />
          </el-form-item>
          <el-form-item label="设置密码" prop="password">
            <el-input
              v-model="form.password"
              :prefix-icon="Lock"
              type="password"
              show-password
              placeholder="至少 8 位，包含字母和数字"
              autocomplete="new-password"
            />
          </el-form-item>
          <el-form-item label="确认密码" prop="confirm_password">
            <el-input
              v-model="form.confirm_password"
              :prefix-icon="Lock"
              type="password"
              show-password
              placeholder="再次输入密码"
              autocomplete="new-password"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button class="submit-button" type="primary" :loading="loading" @click="submit">
            接受邀请并登录
          </el-button>
        </el-form>
        <p class="footer-note">接受邀请后账号立即启用，并自动登录。链接仅可使用一次。</p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.accept-page {
  display: grid;
  min-height: 100vh;
  padding: 40px 20px;
  place-items: center;
  background:
    radial-gradient(circle at 12% 18%, rgba(6, 182, 212, 0.18), transparent 34%),
    radial-gradient(circle at 88% 82%, rgba(59, 130, 246, 0.18), transparent 38%),
    #0c1a33;
}

.accept-card {
  width: min(100%, 460px);
  padding: 40px;
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 24px 70px rgba(9, 20, 42, 0.35);
}

.kicker {
  margin: 0 0 8px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.accept-card h1 {
  margin: 0;
  color: #14213d;
  font-size: 28px;
}

.subtitle {
  margin: 10px 0 24px;
  color: #7b879c;
  font-size: 13px;
  line-height: 1.7;
}

.notice {
  margin-bottom: 18px;
}

.submit-button {
  width: 100%;
  margin-top: 6px;
  border-radius: 10px;
  font-weight: 600;
}

.footer-note {
  margin: 22px 0 0;
  color: #a3adbf;
  font-size: 12px;
  text-align: center;
}

@media (max-width: 560px) {
  .accept-card {
    padding: 28px 22px;
  }
}
</style>
