<script setup lang="ts">
import { ref } from "vue";
import { message } from "ant-design-vue";

const props = defineProps<{ tradeId: number; cancellable: boolean }>();
const emit = defineEmits<{ (e: "cancelled", tradeId: number): void }>();

const loading = ref(false);

async function onConfirm() {
  loading.value = true;
  try {
    emit("cancelled", props.tradeId);
  } catch (e: any) {
    message.error(e.message ?? "撤销失败");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <a-popconfirm
    v-if="cancellable"
    title="确认撤销这笔交易吗？（仅当天可撤销）"
    ok-text="撤销"
    cancel-text="取消"
    @confirm="onConfirm"
  >
    <a-button danger size="small" :loading="loading">撤销</a-button>
  </a-popconfirm>
  <a-button v-else size="small" disabled>不可撤销</a-button>
</template>
