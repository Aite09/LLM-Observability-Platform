export interface Paginated<T> {
  total: number;
  page: number;
  page_size: number;
  items: T[];
}

export interface LLMLog {
  id: string;
  application_id: string;
  model: string;
  provider: string;
  prompt: string;
  response: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_usd: number | null;
  latency_ms: number | null;
  time_to_first_token_ms: number | null;
  status: "success" | "error" | "timeout";
  otel_trace_id: string | null;
  otel_span_id: string | null;
  tags: Record<string, unknown> | null;
  created_at: string;
}

export interface Metric {
  id: string;
  application_id: string;
  model: string;
  period_type: "hourly" | "daily";
  period_start: string;
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  total_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
}

export interface MetricsSummary {
  window: "24h" | "7d" | "30d";
  total_requests: number;
  total_cost_usd: number;
  error_rate: number;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
  cost_prev_window_usd: number;
  open_drift_alerts: number;
}

export interface TestCase {
  id: string;
  suite_name: string;
  input_prompt: string;
  expected_output: string;
  eval_methods: Array<"exact_match" | "embedding_similarity" | "llm_judge">;
  similarity_threshold: number;
  created_at: string;
  updated_at: string;
}

export interface EvalRun {
  id: string;
  suite_name: string;
  commit_sha: string;
  triggered_by: string;
  total_cases: number;
  passed_cases: number;
  pass_rate: number | null;
  gate_threshold: number;
  gate_result: "pass" | "fail" | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface EvalResult {
  id: string;
  eval_run_id: string;
  test_case_id: string;
  exact_match_score: number | null;
  embedding_score: number | null;
  llm_judge_score: number | null;
  llm_judge_reasoning: string | null;
  passed: boolean;
  created_at: string;
}

export interface EvalRunDetail {
  run: EvalRun;
  results: EvalResult[];
}

export interface DriftAlert {
  id: string;
  application_id: string;
  drift_type: string;
  severity: "low" | "medium" | "high" | "critical";
  drift_score: number;
  baseline_stats: Record<string, unknown>;
  current_stats: Record<string, unknown>;
  status: "open" | "acknowledged" | "resolved";
  detected_at: string;
  resolved_at: string | null;
  created_at: string;
}
