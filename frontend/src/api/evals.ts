import { apiGet } from "./client";
import type { EvalRun, EvalRunDetail, Paginated } from "@/types";

export const fetchRuns = (page: number) => apiGet<Paginated<EvalRun>>("/evals/runs", { page, page_size: 50 });
export const fetchRunDetail = (id: string) => apiGet<EvalRunDetail>(`/evals/runs/${id}`);
