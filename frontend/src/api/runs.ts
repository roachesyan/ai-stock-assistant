import client from "./client";
import type { ApiResponse, Run, RunDetail } from "../types";

export interface ListRunsParams {
  page?: number;
  page_size?: number;
  status?: string;
  date?: string;
  risk_verdict?: string;
}

export const listRuns = (params: ListRunsParams = {}) =>
  client.get<ApiResponse<Run[]>>("/runs", { params }).then((r) => r.data);

export const getRun = (runId: string) =>
  client.get<ApiResponse<RunDetail>>(`/runs/${runId}`).then((r) => r.data);

export const triggerRun = (tickers?: string[]) =>
  client
    .post<ApiResponse<{ run_id: string; status: string }>>("/run/trigger", { tickers })
    .then((r) => r.data);

export const cancelRunTrades = (runId: string) =>
  client
    .post<ApiResponse<{ cancelled_count: number }>>(`/runs/${runId}/cancel`)
    .then((r) => r.data);
