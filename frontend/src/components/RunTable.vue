<script setup lang="ts">
import { useRouter } from "vue-router";
import type { Run } from "../types";

defineProps<{ items: Run[]; loading?: boolean }>();
const router = useRouter();

const columns = [
  { title: "日期", dataIndex: "run_date", key: "run_date", width: 120 },
  { title: "状态", dataIndex: "status", key: "status", width: 110 },
  { title: "风控结论", dataIndex: "risk_verdict", key: "risk_verdict", width: 160 },
  { title: "推荐数", dataIndex: "recommendation_count", key: "recommendation_count", width: 90 },
  { title: "交易数", dataIndex: "trade_count", key: "trade_count", width: 90 },
  { title: "创建时间", dataIndex: "created_at", key: "created_at" },
  { title: "操作", key: "op", width: 100 },
];

function verdictColor(v?: string | null) {
  if (v === "APPROVED") return "green";
  if (v === "REJECTED_AT_LIMIT") return "orange";
  return "default";
}

function verdictText(v?: string | null) {
  if (v === "APPROVED") return "通过";
  if (v === "REJECTED_AT_LIMIT") return "⚠️ 未通过仍执行";
  return "—";
}
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
      <template v-if="column.key === 'status'">
        <a-tag :color="record.status === 'ERROR' ? 'red' : 'processing'">{{ record.status }}</a-tag>
      </template>
      <template v-else-if="column.key === 'risk_verdict'">
        <a-tag :color="verdictColor(record.risk_verdict)">{{ verdictText(record.risk_verdict) }}</a-tag>
      </template>
      <template v-else-if="column.key === 'op'">
        <a @click="router.push(`/runs/${record.id}`)">查看</a>
      </template>
    </template>
  </a-table>
</template>
