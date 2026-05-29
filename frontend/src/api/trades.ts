import client from "./client";
import type { ApiResponse, Trade } from "../types";

export interface ListTradesParams {
  page?: number;
  page_size?: number;
  run_id?: string;
  ticker?: string;
  status?: string;
  date?: string;
}

export const listTodayTrades = () =>
  client.get<ApiResponse<Trade[]>>("/trades/today").then((r) => r.data);

export const listTrades = (params: ListTradesParams = {}) =>
  client.get<ApiResponse<Trade[]>>("/trades", { params }).then((r) => r.data);

export const cancelTrade = (tradeId: number) =>
  client.post<ApiResponse<Trade>>(`/trades/${tradeId}/cancel`).then((r) => r.data);
