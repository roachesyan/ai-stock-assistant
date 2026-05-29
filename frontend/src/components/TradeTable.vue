<script setup lang="ts">
import ActionTag from "./ActionTag.vue";
import CancelButton from "./CancelButton.vue";
import type { Trade } from "../types";

defineProps<{ items: Trade[]; loading?: boolean }>();
const emit = defineEmits<{ (e: "cancel", tradeId: number): void }>();

const columns = [
  { title: "股票", dataIndex: "ticker", key: "ticker", width: 90 },
  { title: "方向", dataIndex: "side", key: "side", width: 90 },
  { title: "价格", dataIndex: "price", key: "price", width: 110 },
  { title: "状态", dataIndex: "status", key: "status", width: 110 },
  { title: "执行时间", dataIndex: "executed_at", key: "executed_at" },
  { title: "操作", key: "op", width: 110 },
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
      <template v-if="column.key === 'side'">
        <ActionTag :value="record.side" />
      </template>
      <template v-else-if="column.key === 'price'">
        {{ record.price.toFixed(2) }}
      </template>
      <template v-else-if="column.key === 'status'">
        <a-tag :color="record.status === 'CANCELLED' ? 'default' : 'processing'">
          {{ record.status }}
        </a-tag>
      </template>
      <template v-else-if="column.key === 'op'">
        <CancelButton
          :trade-id="record.id"
          :cancellable="record.cancellable"
          @cancelled="emit('cancel', record.id)"
        />
      </template>
    </template>
  </a-table>
</template>
