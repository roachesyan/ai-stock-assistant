<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { message } from "ant-design-vue";
import { useRunsStore } from "./stores/runs";

const route = useRoute();
const router = useRouter();
const runsStore = useRunsStore();
const triggering = ref(false);

const selectedKeys = computed(() => {
  if (route.path.startsWith("/today")) return ["today"];
  if (route.path.startsWith("/runs")) return ["history"];
  return ["history"];
});

async function onTrigger() {
  triggering.value = true;
  try {
    const res = await runsStore.trigger();
    message.success(`已触发分析 run ${res?.run_id?.slice(0, 8)}…，稍后到「今日交易」查看`);
    router.push("/today");
  } catch (e: any) {
    message.error(e.message ?? "触发失败");
  } finally {
    triggering.value = false;
  }
}
</script>

<template>
  <a-layout style="min-height: 100vh">
    <a-layout-header style="display: flex; align-items: center; gap: 24px">
      <div style="color: #fff; font-weight: 600; font-size: 16px">AI Quant Agent</div>
      <a-menu
        theme="dark"
        mode="horizontal"
        :selected-keys="selectedKeys"
        style="flex: 1; min-width: 0"
      >
        <a-menu-item key="history" @click="router.push('/history')">推荐历史</a-menu-item>
        <a-menu-item key="today" @click="router.push('/today')">今日交易</a-menu-item>
      </a-menu>
      <a-button type="primary" :loading="triggering" @click="onTrigger">触发今日分析</a-button>
    </a-layout-header>

    <a-layout-content style="padding: 24px">
      <a-alert
        type="warning"
        show-icon
        banner
        message="模拟系统：交易经 AI 风控后自动执行，仅供研究，非投资建议。"
        style="margin-bottom: 16px"
      />
      <router-view />
    </a-layout-content>
  </a-layout>
</template>
