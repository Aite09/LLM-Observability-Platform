import { apiGet, apiSend } from "./client";
import type { DriftAlert, Paginated } from "@/types";

export const fetchAlerts = (status?: string) =>
  apiGet<Paginated<DriftAlert>>("/drift/alerts", { status, page_size: 100 });

export const updateAlert = (id: string, status: "acknowledged" | "resolved") =>
  apiSend<DriftAlert>("PATCH", `/drift/alerts/${id}`, { status });
