import { useState } from "react";
import { useEvalRunDetail, useEvalRuns } from "@/hooks/useEvals";
import type { EvalResult } from "@/types";

function GateBadge({ result }: { result: "pass" | "fail" | null }) {
  if (result === null) return <span className="tnum text-[11px] text-faint">pending</span>;
  const tone = result === "pass" ? "text-sage" : "text-rust";
  return <span className={`tnum text-[11px] font-medium uppercase ${tone}`}>{result}</span>;
}

function Score({ v }: { v: number | null }) {
  return <span className="tnum">{v === null ? "—" : Number(v).toFixed(2)}</span>;
}

function ResultRow({ r }: { r: EvalResult }) {
  const [open, setOpen] = useState(false);
  const hasReasoning = r.llm_judge_reasoning !== null && r.llm_judge_reasoning !== "";
  return (
    <>
      <tr
        className={`border-b border-hairline ${hasReasoning ? "cursor-pointer hover:bg-raise/50" : ""} transition-colors duration-150`}
        onClick={() => hasReasoning && setOpen((o) => !o)}
      >
        <td className="tnum px-6 py-2 text-ink-2">{r.test_case_id.slice(0, 8)}</td>
        <td className="py-2 text-right"><Score v={r.exact_match_score} /></td>
        <td className="py-2 text-right"><Score v={r.embedding_score} /></td>
        <td className="py-2 text-right"><Score v={r.llm_judge_score} /></td>
        <td className={`tnum px-6 py-2 text-right text-[11px] font-medium uppercase ${r.passed ? "text-sage" : "text-rust"}`}>
          {r.passed ? "pass" : "fail"}
        </td>
      </tr>
      {open && hasReasoning && (
        <tr className="border-b border-hairline bg-surface">
          <td colSpan={5} className="px-6 py-2 text-xs italic text-ink-2">judge: {r.llm_judge_reasoning}</td>
        </tr>
      )}
    </>
  );
}

export function Evals() {
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const runs = useEvalRuns(page);
  const detail = useEvalRunDetail(selectedId);
  const pages = runs.data ? Math.max(1, Math.ceil(runs.data.total / runs.data.page_size)) : 1;

  return (
    <div className="fade-up">
      <header className="border-b border-rule px-6 py-3.5">
        <h1 className="font-display text-2xl leading-none">Evals</h1>
        <p className="tnum mt-0.5 text-[11px] text-faint">
          {runs.data ? `${runs.data.total} runs · gate threshold blocks CI on fail` : "loading"}
        </p>
      </header>

      {runs.isPending && (
        <div className="space-y-px p-6">{Array.from({ length: 6 }, (_, i) => <div key={i} className="h-8 animate-pulse bg-raise" />)}</div>
      )}
      {runs.isError && (
        <div className="p-6 text-sm text-rust">
          Failed to load runs. <button className="underline hover:text-ink" onClick={() => runs.refetch()}>Retry</button>
        </div>
      )}
      {runs.data && runs.data.items.length === 0 && (
        <p className="p-10 text-center text-sm text-faint">
          No eval runs yet. Trigger one: <code className="tnum">python -m eval.runner --suite core --commit-sha demo</code>
        </p>
      )}

      {runs.data && runs.data.items.length > 0 && (
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-rule text-[10px] uppercase tracking-wide text-faint">
              <th className="px-6 py-2 font-medium">when</th>
              <th className="py-2 font-medium">suite</th>
              <th className="py-2 font-medium">commit</th>
              <th className="py-2 text-right font-medium">passed</th>
              <th className="py-2 text-right font-medium">rate</th>
              <th className="px-6 py-2 text-right font-medium">gate</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.items.map((run) => (
              <tr
                key={run.id}
                onClick={() => setSelectedId(run.id === selectedId ? null : run.id)}
                className={`cursor-pointer border-b border-hairline transition-colors duration-150 hover:bg-raise/50 ${selectedId === run.id ? "bg-raise/60" : ""}`}
              >
                <td className="tnum px-6 py-2 text-ink-2">{new Date(run.created_at).toLocaleString()}</td>
                <td className="py-2">{run.suite_name}</td>
                <td className="tnum py-2 text-ink-2">{run.commit_sha.slice(0, 10)}</td>
                <td className="tnum py-2 text-right">{run.passed_cases}/{run.total_cases}</td>
                <td className="tnum py-2 text-right">{run.pass_rate !== null ? `${(Number(run.pass_rate) * 100).toFixed(1)}%` : "—"}</td>
                <td className="px-6 py-2 text-right"><GateBadge result={run.gate_result} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {runs.data && pages > 1 && (
        <div className="tnum flex items-center justify-between px-6 py-3 text-xs text-ink-2">
          <span>page {page} / {pages}</span>
          <div className="flex gap-1">
            <button className="rounded border border-hairline px-2 py-1 hover:bg-raise disabled:opacity-40" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>prev</button>
            <button className="rounded border border-hairline px-2 py-1 hover:bg-raise disabled:opacity-40" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>next</button>
          </div>
        </div>
      )}

      {selectedId && detail.data && (
        <section className="border-t-2 border-rule">
          <div className="flex items-baseline justify-between px-6 py-3">
            <h2 className="text-sm font-semibold">Run detail — {detail.data.run.suite_name} @ {detail.data.run.commit_sha.slice(0, 10)}</h2>
            <span className="tnum text-[11px] text-faint">
              threshold {Number(detail.data.run.gate_threshold).toFixed(2)} · {detail.data.results.length} cases · click a row for judge reasoning
            </span>
          </div>
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-rule text-[10px] uppercase tracking-wide text-faint">
                <th className="px-6 py-2 font-medium">case</th>
                <th className="py-2 text-right font-medium">exact</th>
                <th className="py-2 text-right font-medium">embed</th>
                <th className="py-2 text-right font-medium">judge</th>
                <th className="px-6 py-2 text-right font-medium">verdict</th>
              </tr>
            </thead>
            <tbody>
              {detail.data.results.map((r) => <ResultRow key={r.id} r={r} />)}
            </tbody>
          </table>
        </section>
      )}
      {selectedId && detail.isPending && <div className="h-24 animate-pulse bg-raise" />}
    </div>
  );
}
