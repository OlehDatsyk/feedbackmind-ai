import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, GitMerge, Pencil, Plus, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { LowSampleBadge, SentimentBadge } from "@/components/badges";
import { NegativeShareLine } from "@/components/charts";
import { Dialog } from "@/components/dialog";
import { FilterBar } from "@/components/FilterBar";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, LoadingBlock, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFilters } from "@/lib/filters";
import { useWsKey } from "@/lib/hooks";
import { fmtPct } from "@/lib/labels";
import type { Feedback, Series, StatTrend, TopicRow } from "@/lib/types";
import { TrendNote } from "./OverviewPage";

interface TopicDetail extends TopicRow {
  examples: Record<string, Feedback[]>;
  series: Series;
  trend: StatTrend;
}

function TopicEditor({ topic, open, onOpenChange }: { topic: TopicRow | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const ws = useWsKey();
  const [name, setName] = useState(topic?.name ?? "");
  const [description, setDescription] = useState(topic?.description ?? "");
  const [keywords, setKeywords] = useState((topic?.keywords ?? []).join(", "));
  const save = useMutation({
    mutationFn: () => {
      const body = { name, description, keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean) };
      return topic?.id ? api(`/api/v1/topics/${topic.id}`, { method: "PATCH", body }) : api("/api/v1/topics", { method: "POST", body });
    },
    onSuccess: () => {
      toast.success(topic?.id ? "Topic updated" : "Topic created. New feedback is matched automatically; use 'Re-apply rules' for existing records.");
      qc.invalidateQueries({ queryKey: [ws] });
      onOpenChange(false);
    },
    onError: (e) => toast.error((e as Error).message),
  });
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={topic?.id ? "Edit topic" : "New topic"}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={save.isPending} disabled={!name.trim()} onClick={() => save.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Name" htmlFor="t-name">
          <Input id="t-name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Description" htmlFor="t-desc">
          <Textarea id="t-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <Field label="Keywords" htmlFor="t-kw" hint="Comma-separated. Whole words match simple plurals/past tense; end with * for a prefix (e.g. deliver*).">
          <Textarea id="t-kw" rows={3} value={keywords} onChange={(e) => setKeywords(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

function TopicPanel({ id }: { id: string }) {
  const ws = useWsKey();
  const { params } = useFilters();
  const q = useQuery({ queryKey: [ws, "topic", id, params], queryFn: () => api<TopicDetail>(`/api/v1/topics/${id}${qs(params)}`) });
  if (q.isLoading) return <LoadingBlock rows={3} />;
  if (q.isError) return <ErrorState error={q.error} />;
  const t = q.data!;
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Negative share over time</h3>
          <TrendNote trend={t.trend} />
        </div>
        <NegativeShareLine buckets={t.series.buckets} granularity={t.series.granularity} height={180} />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {(["negative", "positive", "neutral"] as const).map((label) => (
          <div key={label}>
            <h4 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
              <SentimentBadge label={label} /> examples
            </h4>
            {t.examples[label]?.length ? (
              <ul className="space-y-2">
                {t.examples[label].map((f) => (
                  <li key={f.id}>
                    <Link to={`/feedback/${f.id}`} className="line-clamp-3 text-sm hover:underline">
                      “{f.text}”
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">None.</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function TopicsPage() {
  const ws = useWsKey();
  const qc = useQueryClient();
  const { can } = useAuth();
  const { params } = useFilters();
  const manage = can("topics:manage");
  const q = useQuery({ queryKey: [ws, "topics", params], queryFn: () => api<TopicRow[]>(`/api/v1/topics${qs(params)}`) });
  const sug = useQuery({ queryKey: [ws, "topic-suggestions"], queryFn: () => api<{ suggestions: { term: string; documents: number }[]; note: string; documents: number }>("/api/v1/topics/suggestions"), enabled: false });
  const [editing, setEditing] = useState<TopicRow | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [merge, setMerge] = useState({ source: "", target: "" });

  const act = useMutation({
    mutationFn: ({ path, method, body }: { path: string; method: string; body?: unknown }) => api(path, { method, body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [ws] }),
    onError: (e) => toast.error((e as Error).message),
  });

  const topics = q.data ?? [];
  const pending = topics.filter((t) => t.review_status === "pending_review");

  return (
    <div>
      <PageHeader
        title="Topics"
        description="What customers talk about. Topics come from keyword rules, AI analysis and manual assignment."
        actions={
          manage && (
            <>
              <Button size="sm" variant="outline" onClick={() => act.mutate({ path: "/api/v1/topics/reapply-rules", method: "POST" }, { onSuccess: () => toast.success("Re-applying keyword rules to all records in the background") })}>
                <RefreshCw className="h-3.5 w-3.5" /> Re-apply rules
              </Button>
              <Button size="sm" variant="outline" onClick={() => setMergeOpen(true)}>
                <GitMerge className="h-3.5 w-3.5" /> Merge
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setEditing(null);
                  setEditorOpen(true);
                }}
              >
                <Plus className="h-3.5 w-3.5" /> New topic
              </Button>
            </>
          )
        }
      />
      <FilterBar showSentiment={false} />
      {pending.length > 0 && (
        <Notice tone="blue" className="mb-4" icon={<Sparkles className="h-4 w-4" />}>
          {pending.length} topic{pending.length > 1 ? "s were" : " was"} proposed by AI and await review: approve, rename, merge or delete them.
        </Notice>
      )}
      {q.isLoading && <LoadingBlock rows={8} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {q.data && topics.length === 0 && <EmptyState title="No topics" description="Create a topic with keywords to start grouping feedback." />}
      {topics.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th>Topic</th>
                <th>Records</th>
                <th>Positive</th>
                <th>Negative</th>
                <th>Neutral / mixed</th>
                <th>Negative share</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {topics.map((t) => (
                <Fragment key={t.id}>
                  <tr className="hover:bg-slate-50/60">
                    <td className="min-w-[14rem]">
                      <button className="text-left font-medium hover:underline" onClick={() => setExpanded(expanded === t.id ? null : t.id)} aria-expanded={expanded === t.id}>
                        {t.name}
                      </button>
                      <div className="mt-1 flex flex-wrap gap-1">
                        <Badge tone={t.origin === "ai" ? "violet" : t.origin === "default" ? "slate" : "teal"}>{t.origin === "ai" ? "AI-proposed" : t.origin === "default" ? "Default" : "Custom"}</Badge>
                        {t.review_status === "pending_review" && <Badge tone="amber">Needs review</Badge>}
                        {t.stats?.low_sample && <LowSampleBadge />}
                      </div>
                      {t.keywords.length > 0 && <p className="mt-1 line-clamp-1 text-xs text-muted">Keywords: {t.keywords.join(", ")}</p>}
                    </td>
                    <td className="tabular-nums">
                      <Link to={`/feedback?topic=${t.id}`} className="hover:underline">
                        {t.stats?.count ?? 0}
                      </Link>
                    </td>
                    <td className="tabular-nums">{t.stats?.positive ?? 0}</td>
                    <td className="tabular-nums">{t.stats?.negative ?? 0}</td>
                    <td className="tabular-nums">
                      {t.stats?.neutral ?? 0} / {t.stats?.mixed ?? 0}
                    </td>
                    <td className="tabular-nums">{fmtPct(t.stats?.negative_share)}</td>
                    <td className="whitespace-nowrap text-right">
                      {manage && (
                        <div className="flex justify-end gap-1">
                          {t.review_status === "pending_review" && (
                            <Button size="icon" variant="ghost" aria-label={`Approve ${t.name}`} title="Approve" onClick={() => act.mutate({ path: `/api/v1/topics/${t.id}`, method: "PATCH", body: { review_status: "approved" } })}>
                              <Check className="h-4 w-4" />
                            </Button>
                          )}
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label={`Edit ${t.name}`}
                            title="Edit"
                            onClick={() => {
                              setEditing(t);
                              setEditorOpen(true);
                            }}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            size="icon"
                            variant="ghost"
                            aria-label={`Delete ${t.name}`}
                            title="Delete"
                            onClick={() => {
                              if (window.confirm(`Delete topic "${t.name}"? Feedback records are kept; only the topic links are removed.`)) act.mutate({ path: `/api/v1/topics/${t.id}`, method: "DELETE" });
                            }}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                  {expanded === t.id && (
                    <tr>
                      <td colSpan={7} className="bg-slate-50/50">
                        <TopicPanel id={t.id} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Card title="Suggested topics" description="Frequent distinctive terms in records without a topic (TF-IDF statistics, not AI)." className="mt-5" actions={<Button size="sm" variant="outline" loading={sug.isFetching} onClick={() => sug.refetch()}>Find suggestions</Button>}>
        {!sug.data && <p className="text-sm text-muted">Run the analysis to see candidate topics.</p>}
        {sug.data && sug.data.suggestions.length === 0 && <p className="text-sm text-muted">{sug.data.note}</p>}
        {sug.data && sug.data.suggestions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {sug.data.suggestions.map((s) => (
              <button
                key={s.term}
                disabled={!manage}
                onClick={() => {
                  setEditing({ id: "", name: s.term.replace(/\b\w/g, (c) => c.toUpperCase()), description: "", keywords: [s.term], origin: "custom", review_status: "approved", is_active: true, merged_into_id: null, created_at: "", stats: null });
                  setEditorOpen(true);
                }}
                className="rounded-full border border-line bg-white px-3 py-1 text-sm hover:border-accent-600"
              >
                {s.term} <span className="text-xs text-muted">· {s.documents}</span>
              </button>
            ))}
          </div>
        )}
      </Card>
      {editorOpen && <TopicEditor key={editing?.id || editing?.name || "new"} topic={editing} open={editorOpen} onOpenChange={setEditorOpen} />}
      <Dialog
        open={mergeOpen}
        onOpenChange={setMergeOpen}
        title="Merge duplicate topics"
        description="All feedback links move from the first topic to the second. Keywords are combined; the first topic is kept as an inactive alias."
        footer={
          <>
            <Button variant="outline" onClick={() => setMergeOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={!merge.source || !merge.target || merge.source === merge.target}
              loading={act.isPending}
              onClick={() =>
                act.mutate(
                  { path: "/api/v1/topics/merge", method: "POST", body: { source_id: merge.source, target_id: merge.target } },
                  {
                    onSuccess: () => {
                      toast.success("Topics merged");
                      setMergeOpen(false);
                    },
                  },
                )
              }
            >
              Merge
            </Button>
          </>
        }
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {(["source", "target"] as const).map((k) => (
            <Field key={k} label={k === "source" ? "Merge this topic…" : "…into this topic"} htmlFor={`merge-${k}`}>
              <Select id={`merge-${k}`} value={merge[k]} onChange={(e) => setMerge({ ...merge, [k]: e.target.value })}>
                <option value="">Choose…</option>
                {topics.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </Select>
            </Field>
          ))}
        </div>
      </Dialog>
    </div>
  );
}
