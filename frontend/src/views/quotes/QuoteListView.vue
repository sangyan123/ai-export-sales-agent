<script setup lang="ts">
import ModulePlaceholder from '@/components/ModulePlaceholder.vue'
</script>

<template>
  <ModulePlaceholder
    title="报价中心"
    description="创建报价草案、提交审批、查看版本历史，并导出 PDF / XLSX 报价文件。"
    :features="[
      '报价列表：状态、币种、金额与有效期筛选',
      '报价详情：行项目、价格来源与快照',
      '审批队列：提交、批准、驳回与审批记录',
      '版本管理：复制历史版本并重新审批',
      '导出 PDF / XLSX，不改变报价状态',
    ]"
    api-note="报价计算、生命周期、审批、版本与文档导出接口均已实现，可直接接入列表页。"
  />
</template>
