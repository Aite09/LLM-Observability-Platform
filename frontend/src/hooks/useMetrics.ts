import { useQuery } from "@tanstack/react-query";
import { fetchMetrics, fetchSummary } from "@/api/metrics";

export function useSummary(window: "24h" | "7d" | "30d") {
  return useQuery({
    queryKey: ["summary", window],
    queryFn: () => fetchSummary(window),
    refetchInterval: 30_000,
  });
}

export function useHourlyMetrics(sinceIso: string) {
  return useQuery({
    queryKey: ["metrics", "hourly", sinceIso],
    queryFn: () => fetchMetrics({ period_type: "hourly", start: sinceIso }),
    refetchInterval: 30_000,
  });
}
