<script setup lang="ts">
import ModulePlaceholder from '@/components/ModulePlaceholder.vue'
</script>

<template>
  <ModulePlaceholder
    title="AI 工作台"
    description="查看询盘解析、产品匹配和邮件生成任务的运行状态、失败原因与模型用量。"
    :features="[
      '工作流运行列表与状态轮询',
      '失败原因与错误码查看',
      '取消排队中或运行中的任务',
      '模型调用用量与成本统计（待实现）',
      'Prompt 版本与评测状态（待实现）',
    ]"
    api-note="工作流查询与取消接口已实现；AI 用量统计 /usage/ai 与 Prompt 管理尚未实现。"
  />
</template>
