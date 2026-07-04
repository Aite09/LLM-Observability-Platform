import { apiGet } from "./client";
import type { Metric, MetricsSummary, Paginated } from "@/types";

export const fetchSummary = (window: "24h" | "7d" | "30d") =>
  apiGet<MetricsSummary>("/metrics/summary", { window });

export const fetchMetrics = (params: { period_type?: "hourly" | "daily"; application_id?: string; start?: string; page_size?: number }) =>
  apiGet<Paginated<Metric>>("/metrics", { page_size: 1000, ...params });
