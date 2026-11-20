import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Bot, ChevronLeft, ChevronRight, Flag, Plus, Search, Star, Tag, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { DemoBadge, MethodBadge, SentimentBadge } from "@/components/badges";
import { Dialog } from "@/components/dialog";
import { FilterBar } from "@/components/FilterBar";
import { Badge, Button, EmptyState, ErrorState, Field, Input, LoadingBlock, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api, ApiError, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFilters } from "@/lib/filters";
import { useDebounced, useProducts, useSources, useWsKey } from "@/lib/hooks";
import type { Feedback, Page } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const PAGE = 25;

const schema = z.object({
  text: z.string().trim().min(1, "Feedback text is required").max(20000),
  title: z.string().max(300).optional(),
  product_id: z.string().optional(),
  source_id: z.string().optional(),
  customer_ref: z.string().max(200).optional(),
  customer_segment: z.string().max(120).optional(),
  received_at: z.string().optional(),
  rating: z.string().optional().refine((v) => !v || (!Number.isNaN(Number(v)) && Number(v) >= 0 && Number(v) <= 5), "Rating must be between 0 and 5"),
  tags: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

function NewFeedbackDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const products = useProducts().data ?? [];
  const sources = useSources().data ?? [];
  const [dup, setDup] = useState<string | null>(null);
  const form = useForm<FormValues>({ resolver: zodResolver(schema) });
  const submit = async (v: FormValues, allowDuplicate = false) => {
    const body = {
      text: v.text,
      title: v.title || null,
      product_id: v.product_id || null,
      source_id: v.source_id || null,
      customer_ref: v.customer_ref || null,
      customer_segment: v.customer_segment || null,
      received_at: v.received_at ? new Date(v.received_at).toISOString() : null,
      rating: v.rating ? Number(v.rating) : null,
      rating_max: v.rating ? 5 : null,
      tags: (v.tags ?? "").split(",").map((t) => t.trim()).filter(Boolean),
      allow_duplicate: allowDuplicate,
    };
    try {
      await api<Feedback>("/api/v1/feedback", { method: "POST", body });
      toast.success("Feedback added and analysed");
      qc.invalidateQueries();
      form.reset();
      setDup(null);
      onOpenChange(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setDup(e.message);
      else toast.error((e as Error).message);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Add feedback"
      description="Customer details are optional; anonymous feedback is fine."
      wide
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {dup && (
            <Button variant="outline" onClick={form.handleSubmit((v) => submit(v, true))}>
              Save anyway
            </Button>
          )}
          <Button loading={form.formState.isSubmitting} onClick={form.handleSubmit((v) => submit(v))}>
            Save feedback
          </Button>
        </>
      }
    >
      <form className="grid grid-cols-1 gap-4 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()} noValidate>
        {dup && (
          <Notice tone="amber" className="sm:col-span-2">
            {dup}
          </Notice>
        )}
        <Field label="Feedback text *" htmlFor="text" error={form.formState.errors.text?.message} className="sm:col-span-2">
          <Textarea id="text" rows={5} {...form.register("text")} />
        </Field>
        <Field label="Title / subject" htmlFor="title">
          <Input id="title" {...form.register("title")} />
        </Field>
        <Field label="Date received" htmlFor="received_at" hint="Defaults to now">
          <Input id="received_at" type="datetime-local" {...form.register("received_at")} />
        </Field>
        <Field label="Product / service" htmlFor="product_id">
          <Select id="product_id" {...form.register("product_id")}>
            <option value="">—</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Source" htmlFor="source_id" hint="Defaults to 'Manual entry'">
          <Select id="source_id" {...form.register("source_id")}>
            <option value="">Manual entry</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Rating (0-5)" htmlFor="rating" error={form.formState.errors.rating?.message}>
          <Input id="rating" type="number" step="0.5" min={0} max={5} {...form.register("rating")} />
        </Field>
        <Field label="Customer reference" htmlFor="customer_ref" hint="Optional internal ID - avoid personal data">
          <Input id="customer_ref" {...form.register("customer_ref")} />
        </Field>
        <Field label="Customer segment" htmlFor="customer_segment">
          <Input id="customer_segment" {...form.register("customer_segment")} />
        </Field>
        <Field label="Tags" htmlFor="tags" hint="Comma-separated">
          <Input id="tags" {...form.register("tags")} />
        </Field>
      </form>
    </Dialog>
  );
}

export function FeedbackRow({ f, selected, onToggle }: { f: Feedback; selected?: boolean; onToggle?: () => void }) {
  return (
    <tr className="hover:bg-slate-50/60">
      {onToggle && (
        <td className="w-8">
          <input type="checkbox" checked={selected} onChange={onToggle} aria-label="Select record" className="h-4 w-4 accent-teal-600" />
        </td>
      )}
      <td className="min-w-[18rem]">
        <Link to={`/feedback/${f.id}`} className="line-clamp-2 text-ink hover:underline">
          {f.title ? <strong>{f.title}: </strong> : null}
          {f.text}
        </Link>
        <div className="mt-1 flex flex-wrap gap-1">
          {f.topics.slice(0, 4).map((t) => (
            <Badge key={t.id} tone="teal">
              {t.name}
            </Badge>
          ))}
          {f.tags.map((t) => (
            <Badge key={t.id} tone="slate">
              #{t.name}
            </Badge>
          ))}
          {f.needs_review && <Badge tone="amber">Needs review</Badge>}
          {f.is_archived && <Badge tone="slate">Archived</Badge>}
          {f.is_demo && <DemoBadge />}
        </div>
      </td>
      <td>
        <div className="flex flex-col items-start gap-1">
          <SentimentBadge label={f.sentiment.label} />
          <MethodBadge method={f.sentiment.method} />
        </div>
      </td>
      <td className="whitespace-nowrap text-muted">{f.source?.name ?? "—"}</td>
      <td className="whitespace-nowrap text-muted">{f.product?.name ?? "—"}</td>
      <td className="whitespace-nowrap text-muted">
        {f.rating !== null ? (
          <span className="inline-flex items-center gap-1">
            <Star className="h-3.5 w-3.5" /> {f.rating}/{f.rating_max ?? 5}
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className="whitespace-nowrap text-muted">{formatDate(f.received_at)}</td>
    </tr>
  );
}

export default function FeedbackPage() {
  const ws = useWsKey();
  const qc = useQueryClient();
  const { can } = useAuth();
  const { params } = useFilters();
  const [sp, setSp] = useSearchParams();
  const [search, setSearch] = useState(sp.get("q") ?? "");
  const q = useDebounced(search);
  const [sort, setSort] = useState("newest");
  const [view, setView] = useState<"active" | "review" | "archived">("active");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [newOpen, setNewOpen] = useState(sp.get("new") === "1");
  const topic = sp.get("topic") ?? undefined;

  useEffect(() => {
    setOffset(0);
  }, [q, sort, view, params, topic]);
  const queryParams = useMemo(
    () => ({ ...params, q, sort, limit: PAGE, offset, topic_id: topic ? [topic] : undefined, needs_review: view === "review" ? true : undefined, archived_only: view === "archived" ? true : undefined }),
    [params, q, sort, offset, topic, view],
  );
  const list = useQuery({ queryKey: [ws, "feedback", queryParams], queryFn: () => api<Page<Feedback>>(`/api/v1/feedback${qs(queryParams)}`), placeholderData: (prev) => prev });

  const bulk = useMutation({
    mutationFn: (body: { action: string; tag?: string }) => api<{ updated: number }>("/api/v1/feedback/bulk", { method: "POST", body: { ids: selected, ...body } }),
    onSuccess: (r, v) => {
      toast.success(`${v.action.replace("_", " ")}: ${r.updated} records`);
      setSelected([]);
      qc.invalidateQueries({ queryKey: [ws] });
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const runAI = useMutation({
    mutationFn: () => api<{ records: number }>("/api/v1/analysis/run", { method: "POST", body: { feedback_ids: selected } }),
    onSuccess: (r) => {
      toast.success(`AI analysis queued for ${r.records} records. Results appear when the job finishes.`);
      setSelected([]);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const allSelected = items.length > 0 && items.every((i) => selected.includes(i.id));

  return (
    <div>
      <PageHeader
        title="Feedback"
        description="Search, filter, review and manage every feedback record."
        actions={
          can("feedback:write") && (
            <Button size="sm" onClick={() => setNewOpen(true)}>
              <Plus className="h-3.5 w-3.5" /> Add feedback
            </Button>
          )
        }
      />
      <NewFeedbackDialog
        open={newOpen}
        onOpenChange={(o) => {
          setNewOpen(o);
          if (!o && sp.get("new")) {
            sp.delete("new");
            setSp(sp, { replace: true });
          }
        }}
      />
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" />
          <Input aria-label="Search feedback" placeholder="Search text, title, customer reference or tag…" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
        </div>
        <Select aria-label="View" value={view} onChange={(e) => setView(e.target.value as typeof view)} className="sm:w-44">
          <option value="active">Active records</option>
          <option value="review">Needs review</option>
          <option value="archived">Archived</option>
        </Select>
        <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)} className="sm:w-44">
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="most_negative">Most negative</option>
          <option value="most_positive">Most positive</option>
          <option value="rating_low">Lowest rating</option>
          <option value="rating_high">Highest rating</option>
        </Select>
      </div>
      <FilterBar />
      {topic && (
        <Notice tone="teal" className="mb-3">
          Showing records for one topic.{" "}
          <button
            className="font-medium underline"
            onClick={() => {
              sp.delete("topic");
              setSp(sp);
            }}
          >
            Clear topic filter
          </button>
        </Notice>
      )}
      {selected.length > 0 && can("feedback:write") && (
        <div className="card mb-3 flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm">
          <span className="font-medium">{selected.length} selected</span>
          <Button size="sm" variant="outline" onClick={() => bulk.mutate({ action: view === "archived" ? "unarchive" : "archive" })}>
            <Archive className="h-3.5 w-3.5" /> {view === "archived" ? "Unarchive" : "Archive"}
          </Button>
          <Button size="sm" variant="outline" onClick={() => bulk.mutate({ action: view === "review" ? "clear_review" : "mark_review" })}>
            <Flag className="h-3.5 w-3.5" /> {view === "review" ? "Clear review flag" : "Mark for review"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              const tag = window.prompt("Tag to add to the selected records");
              if (tag?.trim()) bulk.mutate({ action: "add_tag", tag: tag.trim() });
            }}
          >
            <Tag className="h-3.5 w-3.5" /> Add tag
          </Button>
          {can("analysis:run") && (
            <Button size="sm" variant="outline" loading={runAI.isPending} onClick={() => runAI.mutate()}>
              <Bot className="h-3.5 w-3.5" /> Analyse with AI
            </Button>
          )}
          {can("feedback:delete") && (
            <Button
              size="sm"
              variant="danger"
              onClick={() => {
                if (window.confirm(`Permanently delete ${selected.length} records? This cannot be undone. Consider archiving instead.`)) bulk.mutate({ action: "delete" });
              }}
            >
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
            Clear selection
          </Button>
        </div>
      )}
      {list.isLoading && <LoadingBlock rows={8} />}
      {list.isError && <ErrorState error={list.error} onRetry={() => list.refetch()} />}
      {list.data && items.length === 0 && (
        <EmptyState
          title="No feedback found"
          description={q || topic ? "No records match your search and filters." : "Add feedback manually, import a file, or connect an integration."}
          action={
            can("imports:manage") && !q ? (
              <Link to="/imports">
                <Button size="sm">Import data</Button>
              </Link>
            ) : undefined
          }
        />
      )}
      {items.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                {can("feedback:write") && (
                  <th className="w-8">
                    <input
                      type="checkbox"
                      aria-label="Select all on this page"
                      checked={allSelected}
                      onChange={() => setSelected(allSelected ? selected.filter((s) => !items.some((i) => i.id === s)) : [...new Set([...selected, ...items.map((i) => i.id)])])}
                      className="h-4 w-4 accent-teal-600"
                    />
                  </th>
                )}
                <th>Feedback</th>
                <th>Sentiment</th>
                <th>Source</th>
                <th>Product</th>
                <th>Rating</th>
                <th>Received</th>
              </tr>
            </thead>
            <tbody>
              {items.map((f) => (
                <FeedbackRow
                  key={f.id}
                  f={f}
                  selected={selected.includes(f.id)}
                  onToggle={can("feedback:write") ? () => setSelected(selected.includes(f.id) ? selected.filter((s) => s !== f.id) : [...selected, f.id]) : undefined}
                />
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-between gap-2 px-4 py-3 text-sm text-muted">
            <span>
              {offset + 1}–{Math.min(offset + PAGE, total)} of {total.toLocaleString()}
            </span>
            <div className="flex gap-1.5">
              <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} aria-label="Previous page">
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button size="sm" variant="outline" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)} aria-label="Next page">
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
