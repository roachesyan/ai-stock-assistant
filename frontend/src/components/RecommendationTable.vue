<script setup lang="ts">
import ActionTag from "./ActionTag.vue";
import type { Recommendation } from "../types";

defineProps<{ items: Recommendation[]; loading?: boolean }>();

const columns = [
  { title: "股票", dataIndex: "ticker", key: "ticker", width: 90 },
  { title: "操作", dataIndex: "action", key: "action", width: 90 },
  { title: "情绪分", dataIndex: "sentiment_score", key: "sentiment_score", width: 90 },
  { title: "分析价", dataIndex: "price_at_analysis", key: "price_at_analysis", width: 110 },
  { title: "推理", dataIndex: "reasoning", key: "reasoning" },
];
</script>

<template>
  <a-table
    :columns="columns"
    :data-source="items"
    :loading="loading"
    :pagination="false"
    row-key="id"
    size="small"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'action'">
        <ActionTag :value="record.action" />
      </template>
      <template v-else-if="column.key === 'price_at_analysis'">
        {{ record.price_at_analysis.toFixed(2) }}
      </template>
    </template>
  </a-table>
</template>
