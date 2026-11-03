<script setup lang="ts">
import ModulePlaceholder from '@/components/ModulePlaceholder.vue'
</script>

<template>
  <ModulePlaceholder
    title="跟进管理"
    description="按到期时间管理客户跟进任务，记录完成与重新安排，避免询盘和报价被遗忘。"
    :features="[
      '待办列表：按状态、负责人、客户与询盘筛选',
      '到期提醒：PENDING 且已过期的任务',
      '创建任务：关联客户与询盘，指定负责人',
      '完成任务与重新打开',
      '跟进记录与审计事件',
    ]"
    api-note="跟进任务列表、创建、筛选与状态流转接口已实现，可直接接入表格与任务抽屉。"
  />
</template>
