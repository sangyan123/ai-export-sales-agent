<script setup lang="ts">
import ModulePlaceholder from '@/components/ModulePlaceholder.vue'
</script>

<template>
  <ModulePlaceholder
    title="企业设置"
    description="维护企业资料、成员角色、价格规则、邮箱配置与模型配置。"
    :features="[
      '企业资料：公司信息、主营产品与出口市场',
      '成员与角色：邀请、角色调整与停用',
      '价格规则：折扣、底线与审批策略',
      '邮箱与模型 Provider 配置（后续版本）',
      '数据导出与审计查询',
    ]"
    api-note="当前仅有认证、当前用户与审计查询接口；企业资料、成员管理和 Provider 配置待后续实现。"
  />
</template>
