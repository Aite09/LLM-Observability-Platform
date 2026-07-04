import type { ReactNode } from "react";

export function ChartPanel({ title, unit, children, className = "" }: {
  title: string;
  unit?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`border-b border-rule px-6 py-4 ${className}`}>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        {unit && <span className="tnum text-[10px] text-faint">{unit}</span>}
      </div>
      {children}
    </section>
  );
}

/** Shared Recharts props — tokens only, no library default colors. */
export const chartAxis = {
  stroke: "var(--faint)",
  fontSize: 10,
  fontFamily: "var(--font-mono)",
  tickLine: false,
  axisLine: { stroke: "var(--rule)" },
} as const;

export const chartTooltip = {
  contentStyle: {
    background: "var(--bg)",
    border: "1px solid var(--rule)",
    borderRadius: 4,
    fontFamily: "var(--font-mono)",
    fontSize: 11,
    color: "var(--ink)",
  },
} as const;
