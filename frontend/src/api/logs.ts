import { apiGet } from "./client";
import type { LLMLog, Paginated } from "@/types";

export interface LogFilters {
  application_id?: string;
  model?: string;
  status?: string;
  page?: number;
  page_size?: number;
}

export const fetchLogs = (f: LogFilters) => apiGet<Paginated<LLMLog>>("/logs", { page_size: 50, ...f });
export const fetchLog = (id: string) => apiGet<LLMLog>(`/logs/${id}`);
