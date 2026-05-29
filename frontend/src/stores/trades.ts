import { defineStore } from "pinia";
import * as tradesApi from "../api/trades";
import type { Trade } from "../types";

interface TradesState {
  today: Trade[];
  loading: boolean;
}

export const useTradesStore = defineStore("trades", {
  state: (): TradesState => ({
    today: [],
    loading: false,
  }),
  actions: {
    async fetchToday() {
      this.loading = true;
      try {
        const res = await tradesApi.listTodayTrades();
        this.today = res.data ?? [];
      } finally {
        this.loading = false;
      }
    },
    async cancel(tradeId: number) {
      const res = await tradesApi.cancelTrade(tradeId);
      const updated = res.data;
      if (updated) {
        const i = this.today.findIndex((t) => t.id === tradeId);
        if (i >= 0) this.today[i] = updated;
      }
      return updated;
    },
  },
});
