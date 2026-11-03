<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import { Lock, OfficeBuilding, User } from '@element-plus/icons-vue'

import { ApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

interface LoginForm {
  tenant_slug: string
  email: string
  password: string
}

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const formRef = ref<FormInstance>()
const loading = ref(false)
const errorMessage = ref('')
const expired = route.query.expired === '1'

const form = reactive<LoginForm>({
  tenant_slug: '',
  email: '',
  password: '',
})

const rules: FormRules = {
  tenant_slug: [{ required: true, message: '请输入企业标识', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效邮箱', trigger: 'blur' },
  ],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit(): Promise<void> {
  if (!formRef.value) {
    return
  }
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }

  loading.value = true
  errorMessage.value = ''
  try {
    await auth.login({
      tenant_slug: form.tenant_slug.trim(),
      email: form.email.trim(),
      password: form.password,
    })
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : '登录失败，请检查账号信息或稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <section class="brand-panel">
      <div class="brand-badge">F</div>
      <p class="brand-kicker">FASTENER AI EXPORT SALES</p>
      <h1>把询盘、报价与客户跟进<br />放进同一条业务链路</h1>
      <p class="brand-copy">
        AI 负责理解与生成，确定性服务负责价格、权限和审批。面向中国紧固件出口企业的
        轻量销售工作台。
      </p>
      <ul class="feature-list">
        <li><span>01</span>询盘解析与产品匹配</li>
        <li><span>02</span>报价计算、审批与导出</li>
        <li><span>03</span>邮件草案与客户跟进</li>
      </ul>
    </section>

    <section class="form-panel">
      <div class="form-card">
        <header>
          <p class="kicker">欢迎回来</p>
          <h2>登录工作台</h2>
          <p class="subtitle">使用企业管理员分配的账号与企业标识登录。</p>
        </header>

        <el-alert
          v-if="expired"
          class="notice"
          title="登录状态已过期，请重新登录"
          type="warning"
          :closable="false"
          show-icon
        />
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
          <el-form-item label="企业标识" prop="tenant_slug">
            <el-input
              v-model="form.tenant_slug"
              :prefix-icon="OfficeBuilding"
              placeholder="例如 demo"
              autocomplete="organization"
            />
          </el-form-item>
          <el-form-item label="邮箱" prop="email">
            <el-input
              v-model="form.email"
              :prefix-icon="User"
              placeholder="name@company.com"
              autocomplete="username"
            />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              :prefix-icon="Lock"
              type="password"
              show-password
              placeholder="请输入密码"
              autocomplete="current-password"
              @keyup.enter="submit"
            />
          </el-form-item>

          <el-button class="submit-button" type="primary" :loading="loading" @click="submit">
            登录
          </el-button>
        </el-form>

        <p class="footer-note">MVP 演示环境 · 多租户数据隔离</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  display: grid;
  min-height: 100vh;
  grid-template-columns: minmax(0, 1.1fr) minmax(420px, 0.9fr);
  background: #f5f7fb;
}

.brand-panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 64px clamp(40px, 7vw, 112px);
  background:
    radial-gradient(circle at 15% 20%, rgba(6, 182, 212, 0.22), transparent 34%),
    radial-gradient(circle at 85% 75%, rgba(59, 130, 246, 0.22), transparent 38%),
    #0c1a33;
  color: #e8eefb;
}

.brand-badge {
  display: grid;
  width: 52px;
  height: 52px;
  margin-bottom: 28px;
  place-items: center;
  border-radius: 15px;
  background: linear-gradient(135deg, #3b82f6, #06b6d4);
  color: #fff;
  font-size: 24px;
  font-weight: 800;
}

.brand-kicker {
  margin: 0 0 14px;
  color: #7dd3fc;
  font-size: 12px;
  letter-spacing: 0.18em;
}

.brand-panel h1 {
  margin: 0 0 22px;
  font-size: clamp(30px, 3.4vw, 44px);
  line-height: 1.28;
}

.brand-copy {
  max-width: 560px;
  margin: 0 0 36px;
  color: #9fb1cf;
  font-size: 15px;
  line-height: 1.9;
}

.feature-list {
  display: grid;
  gap: 14px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.feature-list li {
  display: flex;
  align-items: center;
  gap: 14px;
  color: #cfdcf1;
  font-size: 14px;
}

.feature-list span {
  color: #5eead4;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
}

.form-panel {
  display: grid;
  padding: 40px;
  place-items: center;
}

.form-card {
  width: min(100%, 420px);
  padding: 40px;
  border: 1px solid #e5e9f2;
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 24px 70px rgba(20, 33, 61, 0.09);
}

.kicker {
  margin: 0 0 8px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.form-card h2 {
  margin: 0;
  color: #14213d;
  font-size: 28px;
}

.subtitle {
  margin: 10px 0 26px;
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
  margin: 24px 0 0;
  color: #a3adbf;
  font-size: 12px;
  text-align: center;
}

@media (max-width: 960px) {
  .login-page {
    grid-template-columns: 1fr;
  }

  .brand-panel {
    display: none;
  }

  .form-panel {
    padding: 24px;
  }
}
</style>
