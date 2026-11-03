<script setup lang="ts">
import { Grid } from '@element-plus/icons-vue'

interface Props {
  title: string
  description: string
  features: string[]
  apiNote: string
}

defineProps<Props>()
</script>

<template>
  <section class="module-page">
    <el-card shadow="never" class="module-card">
      <div class="module-head">
        <div class="module-icon">
          <el-icon :size="24"><Grid /></el-icon>
        </div>
        <div>
          <div class="title-row">
            <h2>{{ title }}</h2>
            <el-tag size="small" effect="plain" type="info">骨架已就绪</el-tag>
          </div>
          <p class="description">{{ description }}</p>
        </div>
      </div>

      <div class="feature-grid">
        <div v-for="(feature, index) in features" :key="feature" class="feature-item">
          <span>{{ String(index + 1).padStart(2, '0') }}</span>
          <p>{{ feature }}</p>
        </div>
      </div>

      <div class="api-note">
        <strong>后端状态</strong>
        <p>{{ apiNote }}</p>
      </div>

      <div class="next-step">
        <el-icon><Grid /></el-icon>
        <span>页面路由、权限守卫与统一 API 客户端已接通，下一步接入列表、详情与操作表单。</span>
      </div>
    </el-card>
  </section>
</template>

<style scoped>
.module-page {
  display: grid;
  gap: 20px;
}

.module-card {
  border-radius: 18px;
}

.module-head {
  display: flex;
  gap: 16px;
  padding-bottom: 22px;
  border-bottom: 1px solid #edf1f7;
}

.module-icon {
  display: grid;
  width: 48px;
  height: 48px;
  flex: none;
  place-items: center;
  border-radius: 14px;
  background: #eff6ff;
  color: #2563eb;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.title-row h2 {
  margin: 0;
  color: #14213d;
  font-size: 24px;
}

.description {
  margin: 8px 0 0;
  color: #7b879c;
  font-size: 14px;
  line-height: 1.8;
}

.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin: 22px 0;
}

.feature-item {
  display: flex;
  gap: 12px;
  padding: 16px;
  border: 1px solid #edf1f7;
  border-radius: 12px;
  background: #fbfcfe;
}

.feature-item span {
  color: #2563eb;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 11px;
  font-weight: 700;
}

.feature-item p {
  margin: 0;
  color: #4c5b74;
  font-size: 13px;
  line-height: 1.6;
}

.api-note {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px 18px;
  border-radius: 12px;
  background: #f6f9ff;
}

.api-note strong {
  flex: none;
  color: #1b2a4a;
  font-size: 13px;
}

.api-note p {
  margin: 0;
  color: #6b7a92;
  font-size: 13px;
  line-height: 1.7;
}

.next-step {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 18px;
  color: #8a97ad;
  font-size: 12px;
}
</style>
