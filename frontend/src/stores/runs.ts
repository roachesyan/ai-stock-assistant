import { defineStore } from "pinia";
import * as runsApi from "../api/runs";
import type { ListRunsParams } from "../api/runs";
import type { Run, RunDetail } from "../types";

interface RunsState {
  runs: Run[];
  total: number;
  current: RunDetail | null;
  loading: boolean;
}

export const useRunsStore = defineStore("runs", {
  state: (): RunsState => ({
    runs: [],
    total: 0,
    current: null,
    loading: false,
  }),
  actions: {
    async fetchRuns(params: ListRunsParams = {}) {
      this.loading = true;
      try {
        const res = await runsApi.listRuns(params);
        this.runs = res.data ?? [];
        this.total = res.meta?.total ?? this.runs.length;
      } finally {
        this.loading = false;
      }
    },
    async fetchRun(runId: string) {
      this.loading = true;
      try {
        const res = await runsApi.getRun(runId);
        this.current = res.data;
        return res.data;
      } finally {
        this.loading = false;
      }
    },
    async trigger(tickers?: string[]) {
      const res = await runsApi.triggerRun(tickers);
      return res.data;
    },
  },
});
