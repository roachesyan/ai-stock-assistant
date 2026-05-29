<script setup lang="ts">
import { onMounted } from "vue";
import { message } from "ant-design-vue";
import TradeTable from "../components/TradeTable.vue";
import { useTradesStore } from "../stores/trades";

const tradesStore = useTradesStore();

async function load() {
  try {
    await tradesStore.fetchToday();
  } catch (e: any) {
    message.error(e.message ?? "加载失败");
  }
}

async function onCancel(tradeId: number) {
  try {
    await tradesStore.cancel(tradeId);
    message.success("已撤销");
  } catch (e: any) {
    message.error(e.message ?? "撤销失败");
    await load();
  }
}

onMounted(load);
</script>

<template>
  <a-card title="今日交易">
    <template #extra>
      <a-button @click="load">刷新</a-button>
    </template>
    <a-empty v-if="!tradesStore.loading && tradesStore.today.length === 0" description="今天还没有交易" />
    <TradeTable
      v-else
      :items="tradesStore.today"
      :loading="tradesStore.loading"
      @cancel="onCancel"
    />
  </a-card>
</template>
