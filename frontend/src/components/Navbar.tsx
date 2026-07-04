import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchAlerts } from "@/api/drift";

const links = [
  { to: "/", label: "Overview" },
  { to: "/logs", label: "Logs" },
  { to: "/evals", label: "Evals" },
  { to: "/drift", label: "Drift" },
];

export function Navbar() {
  const { data } = useQuery({ queryKey: ["alerts", "open"], queryFn: () => fetchAlerts("open"), refetchInterval: 30_000 });
  const openCount = data?.total ?? 0;

  return (
    <nav className="flex h-full w-44 shrink-0 flex-col border-r border-rule bg-surface px-2 py-4">
      <div className="mb-6 flex items-center gap-2 px-2">
        <svg width="14" height="14" viewBox="0 0 12 12" aria-hidden>
          <rect x="1" y="6" width="2" height="5" fill="var(--accent)" />
          <rect x="5" y="3" width="2" height="8" fill="var(--ink-2)" />
          <rect x="9" y="1" width="2" height="10" fill="var(--ink-2)" />
        </svg>
        <span className="font-display text-xl leading-none">llm-obs</span>
      </div>
      {links.map(({ to, label }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          className={({ isActive }) =>
            `flex items-center justify-between rounded px-2 py-1.5 text-sm transition-colors duration-150 ${
              isActive ? "bg-raise text-ink" : "text-ink-2 hover:bg-raise/60 hover:text-ink"
            }`
          }
        >
          <span>{label}</span>
          {label === "Drift" && openCount > 0 && (
            <span className="tnum flex items-center gap-1 text-xs text-accent">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
              {openCount}
            </span>
          )}
        </NavLink>
      ))}
      <div className="tnum mt-auto px-2 text-[10px] text-faint">v0.6.0</div>
    </nav>
  );
}
