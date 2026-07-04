import type { MetricsSummary } from "@/types";

function usd(v: number): string {
  return v.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function LedgerStrip({ s }: { s: MetricsSummary }) {
  const delta = s.cost_prev_window_usd > 0 ? (s.total_cost_usd - s.cost_prev_window_usd) / s.cost_prev_window_usd : null;
  return (
    <div className="flex items-stretch border-b border-rule px-6 py-4">
      <div className="pr-7">
        <div className="text-[11px] text-faint">Spend, {s.window}</div>
        <div className="font-display text-4xl leading-none tracking-tight">{usd(s.total_cost_usd)}</div>
        <div className="tnum mt-1 text-[11px] text-ink-2">
          {delta === null ? "no prior data" : `${delta >= 0 ? "+" : "−"}${Math.abs(delta * 100).toFixed(1)}% vs prior`}
        </div>
      </div>
      <div className="flex flex-col justify-center border-l border-rule px-7">
        <div className="mb-1 text-[11px] text-faint">Latency</div>
        <div className="tnum text-xs leading-relaxed text-ink-2">
          <div>p50 <span className="text-ink">{s.p50_latency_ms ?? "—"}ms</span></div>
          <div>p95 <span className="text-ink">{s.p95_latency_ms ?? "—"}ms</span></div>
          <div>p99 <span className="font-medium text-ink">{s.p99_latency_ms ?? "—"}ms</span></div>
        </div>
      </div>
      <div className="flex flex-col justify-center border-l border-rule px-7">
        <div className="mb-1 text-[11px] text-faint">Requests</div>
        <div className="tnum text-xl font-medium">{s.total_requests.toLocaleString()}</div>
        <div className="tnum mt-0.5 text-[11px] text-ink-2">err {(s.error_rate * 100).toFixed(1)}%</div>
      </div>
      <div className="flex flex-1 flex-col justify-center border-l border-rule px-7">
        <div className="mb-1 text-[11px] text-faint">Attention</div>
        {s.open_drift_alerts > 0 ? (
          <div className="flex items-center gap-2 text-accent">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
            <span className="tnum text-sm font-medium">{s.open_drift_alerts} open drift alert{s.open_drift_alerts > 1 ? "s" : ""}</span>
          </div>
        ) : (
          <div className="text-sm text-sage">all clear</div>
        )}
      </div>
    </div>
  );
}
