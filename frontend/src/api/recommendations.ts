import client from "./client";
import type { ApiResponse, Recommendation } from "../types";

export const getLatest = () =>
  client.get<ApiResponse<Recommendation[]>>("/recommendations/latest").then((r) => r.data);

export const getByDate = (date: string) =>
  client.get<ApiResponse<Recommendation[]>>(`/recommendations/${date}`).then((r) => r.data);

export const getTickerLatest = (ticker: string) =>
  client
    .get<ApiResponse<Recommendation>>(`/recommendations/ticker/${ticker}/latest`)
    .then((r) => r.data);

export const getTickerHistory = (ticker: string, page = 1, page_size = 20) =>
  client
    .get<ApiResponse<Recommendation[]>>(`/recommendations/ticker/${ticker}/history`, {
      params: { page, page_size },
    })
    .then((r) => r.data);
