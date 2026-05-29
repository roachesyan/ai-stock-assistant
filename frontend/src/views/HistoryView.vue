<script setup lang="ts">
import { onMounted, reactive } from "vue";
import { message } from "ant-design-vue";
import type { Dayjs } from "dayjs";
import RunTable from "../components/RunTable.vue";
import { useRunsStore } from "../stores/runs";

const runsStore = useRunsStore();

const filters = reactive({
  page: 1,
  page_size: 20,
  status: undefined as string | undefined,
  risk_verdict: undefined as string | undefined,
  date: undefined as string | undefined,
});

async function load() {
  try {
    await runsStore.fetchRuns({
      page: filters.page,
      page_size: filters.page_size,
      status: filters.status,
      risk_verdict: filters.risk_verdict,
      date: filters.date,
    });
  } catch (e: any) {
    message.error(e.message ?? "加载失败");
  }
}

function onDateChange(d: Dayjs | null) {
  filters.date = d ? d.format("YYYY-MM-DD") : undefined;
  filters.page = 1;
  load();
}

function onPageChange(page: number, pageSize: number) {
  filters.page = page;
  filters.page_size = pageSize;
  load();
}

onMounted(load);
</script>

<template>
  <a-card title="推荐历史">
    <a-space style="margin-bottom: 16px" wrap>
      <a-select
        v-model:value="filters.status"
        placeholder="状态"
        allow-clear
        style="width: 140px"
        @change="() => { filters.page = 1; load(); }"
        :options="[{ value: 'EXECUTED', label: 'EXECUTED' }, { value: 'ERROR', label: 'ERROR' }]"
      />
      <a-select
        v-model:value="filters.risk_verdict"
        placeholder="风控结论"
        allow-clear
        style="width: 200px"
        @change="() => { filters.page = 1; load(); }"
        :options="[
          { value: 'APPROVED', label: '通过' },
          { value: 'REJECTED_AT_LIMIT', label: '未通过仍执行' },
        ]"
      />
      <a-date-picker placeholder="按日期筛选" @change="onDateChange" />
      <a-button @click="load">刷新</a-button>
    </a-space>

    <RunTable :items="runsStore.runs" :loading="runsStore.loading" />

    <a-pagination
      style="margin-top: 16px; text-align: right"
      :current="filters.page"
      :page-size="filters.page_size"
      :total="runsStore.total"
      show-size-changer
      @change="onPageChange"
    />
  </a-card>
</template>
