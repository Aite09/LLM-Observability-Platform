import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { fetchLogs, type LogFilters } from "@/api/logs";

export function useLogs(filters: LogFilters) {
  return useQuery({
    queryKey: ["logs", filters],
    queryFn: () => fetchLogs(filters),
    refetchInterval: 10_000,
    placeholderData: keepPreviousData, // page flips don't blank the table
  });
}
