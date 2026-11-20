import { Filter, X } from "lucide-react";
import { useState } from "react";
import { useFilters } from "@/lib/filters";
import { useProducts, useSources } from "@/lib/hooks";
import { SENTIMENTS, titleCase } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { Button } from "./ui";

function Chips({ options, selected, onChange, label }: { options: { id: string; name: string }[]; selected: string[]; onChange: (v: string[]) => void; label: string }) {
  if (!options.length) return null;
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1.5 text-xs font-medium text-muted">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const on = selected.includes(o.id);
          return (
            <button
              key={o.id}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(on ? selected.filter((x) => x !== o.id) : [...selected, o.id])}
              className={cn("rounded-full border px-2.5 py-1 text-xs transition-colors", on ? "border-accent-600 bg-accent-50 text-accent-700" : "border-line bg-white text-muted hover:text-ink")}
            >
              {o.name}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

/** Source / product / sentiment filters. The date range lives in the top bar and applies everywhere. */
export function FilterBar({ showSentiment = true }: { showSentiment?: boolean }) {
  const { filters, setFilters, activeCount, reset } = useFilters();
  const products = useProducts().data ?? [];
  const sources = useSources().data ?? [];
  const [open, setOpen] = useState(false);
  const count = activeCount - (filters.dateFrom || filters.dateTo ? 1 : 0);
  return (
    <div className="mb-5">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <Filter className="h-3.5 w-3.5" /> Filters{count ? ` (${count})` : ""}
        </Button>
        {activeCount > 0 && (
          <Button variant="ghost" size="sm" onClick={reset}>
            <X className="h-3.5 w-3.5" /> Clear all
          </Button>
        )}
      </div>
      {open && (
        <div className="card mt-2 grid gap-4 p-4 md:grid-cols-3">
          <Chips label="Source" options={sources} selected={filters.sourceIds} onChange={(v) => setFilters({ sourceIds: v })} />
          <Chips label="Product / service" options={products} selected={filters.productIds} onChange={(v) => setFilters({ productIds: v })} />
          {showSentiment && (
            <Chips
              label="Sentiment"
              options={[...SENTIMENTS.map((s) => ({ id: s, name: titleCase(s) })), { id: "unanalyzed", name: "Unclassified" }]}
              selected={filters.sentiments}
              onChange={(v) => setFilters({ sentiments: v })}
            />
          )}
          {!sources.length && !products.length && <p className="text-sm text-muted md:col-span-3">Sources and products appear here once feedback references them.</p>}
        </div>
      )}
    </div>
  );
}
