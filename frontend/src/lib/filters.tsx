/**
 * Global analysis filters (date range, sources, products, sentiments).
 * Shared by the dashboard, feedback list, topics, trends and reports so every view uses the same scope.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useAuth } from "./auth";
import type { QueryValue } from "./api";

export type DatePreset = "all" | "7d" | "30d" | "90d" | "365d" | "custom";

export interface Filters {
  preset: DatePreset;
  dateFrom: string;
  dateTo: string;
  sourceIds: string[];
  productIds: string[];
  sentiments: string[];
}

const EMPTY: Filters = { preset: "all", dateFrom: "", dateTo: "", sourceIds: [], productIds: [], sentiments: [] };

function isoDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function presetRange(preset: DatePreset): { dateFrom: string; dateTo: string } {
  if (preset === "all" || preset === "custom") return { dateFrom: "", dateTo: "" };
  const days = { "7d": 7, "30d": 30, "90d": 90, "365d": 365 }[preset];
  const to = new Date();
  const from = new Date(to);
  from.setDate(from.getDate() - (days - 1));
  return { dateFrom: isoDay(from), dateTo: isoDay(to) };
}

interface FilterValue {
  filters: Filters;
  setFilters: (f: Partial<Filters>) => void;
  reset: () => void;
  params: Record<string, QueryValue>;
  activeCount: number;
}

const Ctx = createContext<FilterValue | null>(null);

function load(key: string): Filters {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return EMPTY;
    const f = { ...EMPTY, ...(JSON.parse(raw) as Partial<Filters>) };
    // Relative presets are recomputed every session so "last 30 days" stays relative to today.
    return f.preset !== "custom" ? { ...f, ...presetRange(f.preset) } : f;
  } catch {
    return EMPTY;
  }
}

export function FilterProvider({ children }: { children: ReactNode }) {
  const { workspace } = useAuth();
  const key = `fm.filters.${workspace?.id ?? "none"}`;
  const [state, setState] = useState<{ key: string; filters: Filters }>(() => ({ key, filters: load(key) }));
  const filters = state.key === key ? state.filters : load(key);

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(filters));
    } catch {
      /* ignore */
    }
  }, [key, filters]);

  const setFilters = useCallback(
    (f: Partial<Filters>) => setState((prev) => ({ key, filters: { ...(prev.key === key ? prev.filters : load(key)), ...f } })),
    [key],
  );
  const reset = useCallback(() => setState({ key, filters: EMPTY }), [key]);

  const value = useMemo<FilterValue>(() => {
    const params: Record<string, QueryValue> = {
      date_from: filters.dateFrom || undefined,
      date_to: filters.dateTo || undefined,
      source_id: filters.sourceIds,
      product_id: filters.productIds,
      sentiment: filters.sentiments,
    };
    const activeCount = (filters.dateFrom || filters.dateTo ? 1 : 0) + filters.sourceIds.length + filters.productIds.length + filters.sentiments.length;
    return { filters, setFilters, reset, params, activeCount };
  }, [filters, setFilters, reset]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useFilters(): FilterValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useFilters must be used inside FilterProvider");
  return v;
}
