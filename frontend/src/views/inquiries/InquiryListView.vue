<script setup lang="ts">
import ModulePlaceholder from '@/components/ModulePlaceholder.vue'
</script>

<template>
  <ModulePlaceholder
    title="询盘管理"
    description="集中处理原始询盘、AI 解析结果、人工确认字段、产品匹配候选与关联报价。"
    :features="[
      '询盘列表与状态筛选：RECEIVED、PARSING、NEEDS_INFO、MATCHED 等',
      '询盘详情：原始邮件正文、附件与对话记录',
      'AI 解析：字段置信度、缺失项与人工确认',
      '产品匹配：候选排序、冲突字段与解释',
      '从询盘生成报价与邮件草案',
    ]"
    api-note="询盘 CRUD、附件、解析、需求确认与匹配接口已实现；EML 导入和附件预览待后续里程碑。"
  />
</template>
