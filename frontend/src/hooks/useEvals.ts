import { useQuery } from "@tanstack/react-query";
import { fetchRunDetail, fetchRuns } from "@/api/evals";

export function useEvalRuns(page: number) {
  return useQuery({
    queryKey: ["eval-runs", page],
    queryFn: () => fetchRuns(page),
    refetchInterval: 30_000,
  });
}

export function useEvalRunDetail(id: string | null) {
  return useQuery({
    queryKey: ["eval-run", id],
    queryFn: () => fetchRunDetail(id as string),
    enabled: id !== null,
  });
}
