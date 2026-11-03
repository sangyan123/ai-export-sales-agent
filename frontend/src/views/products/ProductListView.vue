<script setup lang="ts">
import ModulePlaceholder from '@/components/ModulePlaceholder.vue'
</script>

<template>
  <ModulePlaceholder
    title="产品中心"
    description="维护螺栓、螺母、螺钉、垫圈等产品规格，以及价格表和阶梯价。"
    :features="[
      '产品列表：品类、标准、材质、规格与启停用',
      '产品详情：规格字段、MOQ、包装与属性',
      '价格表与阶梯价维护',
      'Excel 模板导入与导入结果查询（待实现）',
      '知识资料上传与解析状态（待实现）',
    ]"
    api-note="产品 CRUD、价格表与阶梯价接口已实现；Excel 导入、模板下载和知识资料接口尚未实现。"
  />
</template>
