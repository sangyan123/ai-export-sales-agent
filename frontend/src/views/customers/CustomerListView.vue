<script setup lang="ts">
import ModulePlaceholder from '@/components/ModulePlaceholder.vue'
</script>

<template>
  <ModulePlaceholder
    title="客户管理"
    description="管理客户档案、联系人、专属价格与询盘历史，形成客户业务时间线。"
    :features="[
      '客户列表：公司、国家、来源与负责人',
      '客户详情与备注',
      '联系人维护：主联系人、邮箱、电话与语言',
      '客户专属价与审批状态',
      '关联询盘、报价与跟进记录',
    ]"
    api-note="客户 CRUD、专属价以及联系人接口已实现；客户备注和完整时间线待后续补齐。"
  />
</template>
