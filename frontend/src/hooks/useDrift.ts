import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchAlerts, updateAlert } from "@/api/drift";
import type { DriftAlert, Paginated } from "@/types";

export function useDriftAlerts(status?: string) {
  return useQuery({
    queryKey: ["drift-alerts", status ?? "all"],
    queryFn: () => fetchAlerts(status),
    refetchInterval: 30_000,
  });
}

export function useUpdateAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: "acknowledged" | "resolved" }) => updateAlert(id, status),
    // Optimistic: flip status locally, roll back on error
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: ["drift-alerts"] });
      const snapshots = qc.getQueriesData<Paginated<DriftAlert>>({ queryKey: ["drift-alerts"] });
      for (const [key, data] of snapshots) {
        if (!data) continue;
        qc.setQueryData(key, {
          ...data,
          items: data.items.map((a) => (a.id === id ? { ...a, status } : a)),
        });
      }
      return { snapshots };
    },
    onError: (_err, _vars, ctx) => {
      for (const [key, data] of ctx?.snapshots ?? []) qc.setQueryData(key, data);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["drift-alerts"] });
      void qc.invalidateQueries({ queryKey: ["alerts", "open"] }); // sidebar count
    },
  });
}
