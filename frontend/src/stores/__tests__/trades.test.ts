import { describe, it, expect, beforeEach, vi } from "vitest";
import { setActivePinia, createPinia } from "pinia";
import { useTradesStore } from "../trades";
import type { Trade } from "../../types";

vi.mock("../../api/trades", () => ({
  listTodayTrades: vi.fn(),
  cancelTrade: vi.fn(),
}));

import * as tradesApi from "../../api/trades";

const baseTrade: Trade = {
  id: 1,
  run_id: "r1",
  run_date: "2025-01-15",
  ticker: "AAPL",
  side: "BUY",
  price: 200,
  status: "EXECUTED",
  executed_at: "2025-01-15T10:00:00",
  cancelled_at: null,
  cancellable: true,
};

describe("trades store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("fetchToday fills today list", async () => {
    (tradesApi.listTodayTrades as any).mockResolvedValue({ success: true, data: [baseTrade] });
    const store = useTradesStore();
    await store.fetchToday();
    expect(store.today).toHaveLength(1);
    expect(store.today[0].ticker).toBe("AAPL");
  });

  it("cancel updates the trade status to CANCELLED", async () => {
    (tradesApi.listTodayTrades as any).mockResolvedValue({ success: true, data: [baseTrade] });
    (tradesApi.cancelTrade as any).mockResolvedValue({
      success: true,
      data: { ...baseTrade, status: "CANCELLED", cancellable: false },
    });

    const store = useTradesStore();
    await store.fetchToday();
    await store.cancel(1);
    expect(store.today[0].status).toBe("CANCELLED");
    expect(store.today[0].cancellable).toBe(false);
  });
});
