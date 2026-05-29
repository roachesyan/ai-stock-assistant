<script setup lang="ts">
import { onMounted, ref } from "vue";
import { message } from "ant-design-vue";
import RiskReviewCard from "../components/RiskReviewCard.vue";
import RecommendationTable from "../components/RecommendationTable.vue";
import TradeTable from "../components/TradeTable.vue";
import { useRunsStore } from "../stores/runs";
import { cancelTrade } from "../api/trades";

const props = defineProps<{ runId: string }>();
const runsStore = useRunsStore();
const loading = ref(false);

async function load() {
  loading.value = true;
  try {
    await runsStore.fetchRun(props.runId);
  } catch (e: any) {
    message.error(e.message ?? "加载失败");
  } finally {
    loading.value = false;
  }
}

async function onCancel(tradeId: number) {
  try {
    await cancelTrade(tradeId);
    message.success("已撤销");
    await load();
  } catch (e: any) {
    message.error(e.message ?? "撤销失败");
  }
}

onMounted(load);
</script>

<template>
  <a-spin :spinning="loading">
    <template v-if="runsStore.current">
      <a-descriptions title="运行详情" bordered size="small" :column="3" style="margin-bottom: 16px">
        <a-descriptions-item label="Run ID" :span="3">{{ runsStore.current.id }}</a-descriptions-item>
        <a-descriptions-item label="日期">{{ runsStore.current.run_date }}</a-descriptions-item>
        <a-descriptions-item label="状态">{{ runsStore.current.status }}</a-descriptions-item>
        <a-descriptions-item label="风控结论">{{ runsStore.current.risk_verdict ?? "—" }}</a-descriptions-item>
        <a-descriptions-item label="创建时间" :span="3">{{ runsStore.current.created_at }}</a-descriptions-item>
        <a-descriptions-item v-if="runsStore.current.error_message" label="错误" :span="3">
          {{ runsStore.current.error_message }}
        </a-descriptions-item>
      </a-descriptions>

      <RiskReviewCard
        :review="runsStore.current.risk_review"
        :verdict="runsStore.current.risk_verdict"
        :risk-rounds="runsStore.current.risk_rounds"
        :evidence-rounds="runsStore.current.evidence_rounds"
        style="margin-bottom: 16px"
      />

      <a-card title="分析建议" size="small" style="margin-bottom: 16px">
        <RecommendationTable :items="runsStore.current.recommendations" />
      </a-card>

      <a-card title="交易" size="small">
        <TradeTable :items="runsStore.current.trades" @cancel="onCancel" />
      </a-card>
    </template>
    <a-empty v-else-if="!loading" description="未找到该运行" />
  </a-spin>
</template>
