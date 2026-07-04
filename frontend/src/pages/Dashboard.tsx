import { useMemo, useState } from "react";
import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import { ChartPanel, chartAxis, chartTooltip } from "@/components/ChartPanel";
import { LedgerStrip } from "@/components/LedgerStrip";
import { useHourlyMetrics, useSummary } from "@/hooks/useMetrics";

type Win = "24h" | "7d" | "30d";
const WINDOW_HOURS: Record<Win, number> = { "24h": 24, "7d": 168, "30d": 720 };

export function Dashboard() {
  const [win, setWin] = useState<Win>("7d");
  const summary = useSummary(win);
  const since = useMemo(
    () => new Date(Date.now() - WINDOW_HOURS[win] * 3600_000).toISOString(),
    [win],
  );
  const metrics = useHourlyMetrics(since);

  const series = useMemo(() => {
    const byHour = new Map<string, { t: string; cost: number; p50: number | null; p95: number | null; p99: number | null; requests: number }>();
    for (const m of metrics.data?.items ?? []) {
      const key = m.period_start;
      const cur = byHour.get(key) ?? { t: key, cost: 0, p50: null, p95: null, p99: null, requests: 0 };
      cur.cost += Number(m.total_cost_usd);
      cur.requests += m.total_requests;
      cur.p50 = m.p50_latency_ms ?? cur.p50;
      cur.p95 = m.p95_latency_ms ?? cur.p95;
      cur.p99 = m.p99_latency_ms ?? cur.p99;
      byHour.set(key, cur);
    }
    return [...byHour.values()].sort((a, b) => a.t.localeCompare(b.t))
      .map((r) => ({ ...r, label: new Date(r.t).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric" }) }));
  }, [metrics.data]);

  if (summary.isPending) {
    return <div className="space-y-3 p-6">{[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse rounded bg-raise" />)}</div>;
  }
  if (summary.isError) {
    return (
      <div className="p-6 text-sm text-rust">
        Could not load metrics — is the API running?{" "}
        <button className="underline hover:text-ink" onClick={() => summary.refetch()}>Retry</button>
      </div>
    );
  }

  return (
    <div className="fade-up">
      <header className="flex items-center justify-between border-b border-rule px-6 py-3.5">
        <div>
          <h1 className="font-display text-2xl leading-none">Overview</h1>
          <p className="tnum mt-0.5 text-[11px] text-faint">all applications · refreshes every 30s</p>
        </div>
        <div className="flex overflow-hidden rounded border border-hairline text-xs" role="tablist" aria-label="Time window">
          {(["24h", "7d", "30d"] as const).map((w) => (
            <button
              key={w}
              role="tab"
              aria-selected={win === w}
              onClick={() => setWin(w)}
              className={`px-3 py-1 transition-colors duration-150 ${win === w ? "bg-raise text-ink" : "text-ink-2 hover:text-ink"}`}
            >
              {w}
            </button>
          ))}
        </div>
      </header>

      <LedgerStrip s={summary.data} />

      <ChartPanel title="Spend over time" unit="USD/hour">
        {series.length === 0 ? (
          <p className="py-8 text-center text-sm text-faint">No rollups yet — the metrics worker aggregates every 5 minutes. Seed demo data with <code className="tnum">python -m scripts.seed</code>.</p>
        ) : (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={series} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="var(--hairline)" strokeDasharray="0" vertical={false} />
              <XAxis dataKey="label" {...chartAxis} minTickGap={48} />
              <YAxis {...chartAxis} />
              <Tooltip {...chartTooltip} />
              <Area dataKey="cost" stroke="var(--ink)" strokeWidth={1.5} fill="var(--accent-soft)" isAnimationActive={false} name="USD" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </ChartPanel>

      <ChartPanel title="Latency percentiles" unit="hourly · ms">
        {series.length === 0 ? (
          <p className="py-8 text-center text-sm text-faint">No latency data in this window.</p>
        ) : (
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={series} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
              <CartesianGrid stroke="var(--hairline)" vertical={false} />
              <XAxis dataKey="label" {...chartAxis} minTickGap={48} />
              <YAxis {...chartAxis} />
              <Tooltip {...chartTooltip} />
              <Line dataKey="p50" stroke="var(--faint)" strokeWidth={1} dot={false} isAnimationActive={false} />
              <Line dataKey="p95" stroke="var(--ink-2)" strokeWidth={1} dot={false} isAnimationActive={false} />
              <Line dataKey="p99" stroke="var(--ink)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
        <div className="tnum mt-1 flex gap-4 text-[10px]">
          <span className="text-faint">━ p50</span>
          <span className="text-ink-2">━ p95</span>
          <span className="text-ink">━ p99</span>
        </div>
      </ChartPanel>
    </div>
  );
}
