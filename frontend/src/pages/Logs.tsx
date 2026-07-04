import { useState } from "react";
import { useLogs } from "@/hooks/useLogs";
import type { LLMLog } from "@/types";

const inputCls =
  "rounded border border-hairline bg-bg px-2 py-1 text-xs text-ink placeholder:text-faint focus-visible:border-accent disabled:opacity-50";

function StatusMark({ s }: { s: LLMLog["status"] }) {
  const tone = s === "success" ? "text-sage" : "text-rust";
  return <span className={`tnum text-[11px] font-medium uppercase ${tone}`}>{s}</span>;
}

export function Logs() {
  const [app, setApp] = useState("");
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<LLMLog | null>(null);

  const q = useLogs({
    application_id: app || undefined,
    model: model || undefined,
    status: status || undefined,
    page,
  });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;

  return (
    <div className="fade-up">
      <header className="flex items-center justify-between border-b border-rule px-6 py-3.5">
        <div>
          <h1 className="font-display text-2xl leading-none">Logs</h1>
          <p className="tnum mt-0.5 text-[11px] text-faint">{q.data ? `${q.data.total.toLocaleString()} records · refreshes every 10s` : "loading"}</p>
        </div>
        <div className="flex gap-2">
          <input className={inputCls} placeholder="application" value={app} onChange={(e) => { setApp(e.target.value); setPage(1); }} />
          <input className={inputCls} placeholder="model" value={model} onChange={(e) => { setModel(e.target.value); setPage(1); }} />
          <select className={inputCls} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="status filter">
            <option value="">any status</option>
            <option value="success">success</option>
            <option value="error">error</option>
            <option value="timeout">timeout</option>
          </select>
        </div>
      </header>

      {q.isPending && (
        <div className="space-y-px p-6">{Array.from({ length: 8 }, (_, i) => <div key={i} className="h-8 animate-pulse bg-raise" />)}</div>
      )}
      {q.isError && (
        <div className="p-6 text-sm text-rust">
          Failed to load logs. <button className="underline hover:text-ink" onClick={() => q.refetch()}>Retry</button>
        </div>
      )}
      {q.data && q.data.items.length === 0 && (
        <p className="p-10 text-center text-sm text-faint">
          No logs match. Send one with <code className="tnum">POST /logs</code> or run <code className="tnum">python -m scripts.seed</code>.
        </p>
      )}

      {q.data && q.data.items.length > 0 && (
        <>
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-rule text-[10px] uppercase tracking-wide text-faint">
                <th className="px-6 py-2 font-medium">time</th>
                <th className="py-2 font-medium">application</th>
                <th className="py-2 font-medium">model</th>
                <th className="py-2 text-right font-medium">latency</th>
                <th className="py-2 text-right font-medium">cost</th>
                <th className="px-6 py-2 text-right font-medium">status</th>
              </tr>
            </thead>
            <tbody>
              {q.data.items.map((log) => (
                <tr
                  key={log.id}
                  onClick={() => setSelected(log)}
                  className="cursor-pointer border-b border-hairline transition-colors duration-150 hover:bg-raise/50"
                >
                  <td className="tnum px-6 py-2 text-ink-2">{new Date(log.created_at).toLocaleString()}</td>
                  <td className="py-2">{log.application_id}</td>
                  <td className="tnum py-2 text-ink-2">{log.model}</td>
                  <td className="tnum py-2 text-right">{log.latency_ms != null ? `${log.latency_ms}ms` : "—"}</td>
                  <td className="tnum py-2 text-right">{log.cost_usd != null ? `$${Number(log.cost_usd).toFixed(4)}` : "—"}</td>
                  <td className="px-6 py-2 text-right"><StatusMark s={log.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="tnum flex items-center justify-between px-6 py-3 text-xs text-ink-2">
            <span>page {q.data.page} / {pages}</span>
            <div className="flex gap-1">
              <button className="rounded border border-hairline px-2 py-1 hover:bg-raise disabled:opacity-40" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>prev</button>
              <button className="rounded border border-hairline px-2 py-1 hover:bg-raise disabled:opacity-40" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>next</button>
            </div>
          </div>
        </>
      )}

      {selected && (
        <aside className="fixed inset-y-0 right-0 z-10 w-[480px] overflow-y-auto border-l border-rule bg-bg p-6 shadow-xl" role="dialog" aria-label="Log detail">
          <div className="mb-4 flex items-start justify-between">
            <div>
              <h2 className="font-display text-xl">{selected.model}</h2>
              <p className="tnum text-[11px] text-faint">{selected.id}</p>
            </div>
            <button className="rounded border border-hairline px-2 py-1 text-xs hover:bg-raise" onClick={() => setSelected(null)}>close</button>
          </div>
          <dl className="tnum grid grid-cols-2 gap-x-4 gap-y-2 border-b border-rule pb-4 text-xs">
            <dt className="text-faint">application</dt><dd>{selected.application_id}</dd>
            <dt className="text-faint">provider</dt><dd>{selected.provider}</dd>
            <dt className="text-faint">status</dt><dd><StatusMark s={selected.status} /></dd>
            <dt className="text-faint">latency</dt><dd>{selected.latency_ms ?? "—"}ms</dd>
            <dt className="text-faint">tokens</dt><dd>{selected.total_tokens ?? "—"}</dd>
            <dt className="text-faint">cost</dt><dd>{selected.cost_usd != null ? `$${Number(selected.cost_usd).toFixed(6)}` : "—"}</dd>
            <dt className="text-faint">trace</dt><dd className="break-all">{selected.otel_trace_id ?? "—"}</dd>
            <dt className="text-faint">span</dt><dd>{selected.otel_span_id ?? "—"}</dd>
          </dl>
          <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wide text-faint">prompt</h3>
          <pre className="tnum whitespace-pre-wrap rounded border border-hairline bg-surface p-3 text-xs">{selected.prompt}</pre>
          <h3 className="mb-1 mt-4 text-[10px] uppercase tracking-wide text-faint">response</h3>
          <pre className="tnum whitespace-pre-wrap rounded border border-hairline bg-surface p-3 text-xs">{selected.response ?? "(no response — call failed)"}</pre>
        </aside>
      )}
    </div>
  );
}
