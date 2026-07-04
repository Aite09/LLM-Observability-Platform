import { useState } from "react";
import { useDriftAlerts, useUpdateAlert } from "@/hooks/useDrift";
import type { DriftAlert } from "@/types";

const SEVERITY_TONE: Record<DriftAlert["severity"], string> = {
  low: "text-ink-2",
  medium: "text-accent",
  high: "text-accent",
  critical: "text-rust",
};

function StatRow({ label, stats }: { label: string; stats: Record<string, unknown> }) {
  return (
    <div className="tnum text-[11px] text-ink-2">
      <span className="text-faint">{label}:</span>{" "}
      {Object.entries(stats).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(" · ") || "—"}
    </div>
  );
}

export function DriftAlerts() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const q = useDriftAlerts(statusFilter || undefined);
  const mutation = useUpdateAlert();

  return (
    <div className="fade-up">
      <header className="flex items-center justify-between border-b border-rule px-6 py-3.5">
        <div>
          <h1 className="font-display text-2xl leading-none">Drift</h1>
          <p className="tnum mt-0.5 text-[11px] text-faint">
            prompt-distribution shifts vs 7-day baseline · detector runs hourly
          </p>
        </div>
        <div className="flex overflow-hidden rounded border border-hairline text-xs" role="tablist" aria-label="Status filter">
          {["", "open", "acknowledged", "resolved"].map((s) => (
            <button
              key={s || "all"}
              role="tab"
              aria-selected={statusFilter === s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1 transition-colors duration-150 ${statusFilter === s ? "bg-raise text-ink" : "text-ink-2 hover:text-ink"}`}
            >
              {s || "all"}
            </button>
          ))}
        </div>
      </header>

      {q.isPending && (
        <div className="space-y-3 p-6">{[0, 1].map((i) => <div key={i} className="h-24 animate-pulse rounded bg-raise" />)}</div>
      )}
      {q.isError && (
        <div className="p-6 text-sm text-rust">
          Failed to load alerts. <button className="underline hover:text-ink" onClick={() => q.refetch()}>Retry</button>
        </div>
      )}
      {q.data && q.data.items.length === 0 && (
        <p className="p-10 text-center text-sm text-faint">
          No {statusFilter || ""} drift alerts — input distribution is stable. The detector compares each app&apos;s last 24h of prompt embeddings against its 7-day baseline.
        </p>
      )}

      {q.data?.items.map((alert) => (
        <article key={alert.id} className="border-b border-rule px-6 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                {alert.status === "open" && <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />}
                <span className={`tnum text-[11px] font-semibold uppercase ${SEVERITY_TONE[alert.severity]}`}>{alert.severity}</span>
                <span className="text-sm font-semibold">{alert.application_id}</span>
                <span className="tnum text-[11px] text-faint">score {Number(alert.drift_score).toFixed(4)}</span>
              </div>
              <p className="tnum mt-1 text-[11px] text-faint">
                {alert.drift_type} · detected {new Date(alert.detected_at).toLocaleString()}
                {alert.resolved_at && ` · resolved ${new Date(alert.resolved_at).toLocaleString()}`}
              </p>
              <div className="mt-2 space-y-0.5">
                <StatRow label="baseline" stats={alert.baseline_stats} />
                <StatRow label="current" stats={alert.current_stats} />
              </div>
            </div>
            <div className="flex shrink-0 gap-2">
              {alert.status === "open" && (
                <button
                  className="rounded border border-hairline px-3 py-1 text-xs hover:bg-raise disabled:opacity-40"
                  disabled={mutation.isPending}
                  onClick={() => mutation.mutate({ id: alert.id, status: "acknowledged" })}
                >
                  acknowledge
                </button>
              )}
              {alert.status !== "resolved" && (
                <button
                  className="rounded border border-hairline px-3 py-1 text-xs text-sage hover:bg-raise disabled:opacity-40"
                  disabled={mutation.isPending}
                  onClick={() => mutation.mutate({ id: alert.id, status: "resolved" })}
                >
                  resolve
                </button>
              )}
              {alert.status === "resolved" && <span className="tnum text-[11px] uppercase text-sage">resolved</span>}
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}
