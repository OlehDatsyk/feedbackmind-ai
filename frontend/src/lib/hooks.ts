import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api";
import { useAuth } from "./auth";
import type { Job, Product, Source } from "./types";

/** Query key prefix that includes the workspace, so cached data never leaks between workspaces. */
export function useWsKey(): string {
  return useAuth().workspace?.id ?? "none";
}

export function useProducts() {
  const ws = useWsKey();
  return useQuery({ queryKey: [ws, "products"], queryFn: () => api<Product[]>("/api/v1/products") });
}

export function useSources() {
  const ws = useWsKey();
  return useQuery({ queryKey: [ws, "sources"], queryFn: () => api<Source[]>("/api/v1/sources") });
}

export function useTags() {
  const ws = useWsKey();
  return useQuery({ queryKey: [ws, "tags"], queryFn: () => api<{ id: string; name: string }[]>("/api/v1/tags") });
}

/** Poll a background job until it finishes. */
export function useJob(jobId: string | null | undefined) {
  const ws = useWsKey();
  return useQuery({
    queryKey: [ws, "job", jobId],
    queryFn: () => api<Job>(`/api/v1/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && ["succeeded", "failed"].includes(q.state.data.status) ? false : 1500),
  });
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}
