import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, CheckCircle2, Lightbulb, Minus, Sparkles, XCircle } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { AIGeneratedBadge, ImportanceBadge, SentimentBadge, StrengthBadge } from "@/components/badges";
import { Dialog } from "@/components/dialog";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingBlock, Notice, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFilters } from "@/lib/filters";
import { useWsKey } from "@/lib/hooks";
import { INSIGHT_KINDS } from "@/lib/labels";
import type { Insight } from "@/lib/types";
import { formatDate } from "@/lib/utils";

function TrendIcon({ dir }: { dir: Insight["trend_direction"] }) {
  if (dir === "up") return <Badge tone="red"><ArrowUpRight className="h-3 w-3" /> Increasing</Badge>;
  if (dir === "down") return <Badge tone="green"><ArrowDownRight className="h-3 w-3" /> Decreasing</Badge>;
  if (dir === "flat") return <Badge tone="slate"><Minus className="h-3 w-3" /> No significant change</Badge>;
  return <Badge tone="slate">Trend: not enough data</Badge>;
}

function InsightDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const ws = useWsKey();
  const q = useQuery({ queryKey: [ws, "insight", id], queryFn: () => api<Insight>(`/api/v1/insights/${id}`) });
  const i = q.data;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={i?.title ?? "Insight"} wide>
      {q.isLoading && <LoadingBlock />}
      {q.isError && <ErrorState error={q.error} />}
      {i && (
        <div className="space-y-4 text-sm">
          <div className="flex flex-wrap gap-1.5">
            <Badge tone="navy">{INSIGHT_KINDS[i.kind] ?? i.kind}</Badge>
            <ImportanceBadge importance={i.importance} />
            <StrengthBadge strength={i.evidence_strength} n={i.supporting_count} />
            <TrendIcon dir={i.trend_direction} />
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Observed facts (computed from data)</h3>
            <p>{i.description}</p>
            <p className="mt-1 text-xs text-muted">
              Period: {formatDate(i.period_start)} – {formatDate(i.period_end)} · {i.supporting_count} supporting records
            </p>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Suggested action (rule-based)</h3>
            <p>{i.suggested_action}</p>
          </div>
          {i.ai_summary && (
            <div className="rounded-lg border border-violet-200 bg-violet-50/60 p-3">
              <div className="mb-1">
                <AIGeneratedBadge model={i.ai_model} />
              </div>
              <p>{i.ai_summary}</p>
              {i.ai_suggested_action && (
                <p className="mt-2">
                  <strong>AI-suggested action:</strong> {i.ai_suggested_action}
                </p>
              )}
              <p className="mt-2 text-xs text-muted">AI interpretation of the facts above; verify before acting.</p>
            </div>
          )}
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Supporting feedback (sample)</h3>
            <ul className="space-y-2">
              {i.evidence?.map((f) => (
                <li key={f.id} className="rounded-lg border border-line p-3">
                  <div className="mb-1 flex items-center gap-2">
                    <SentimentBadge label={f.sentiment.label} />
                    <span className="text-xs text-muted">{formatDate(f.received_at)}</span>
                  </div>
                  <Link to={`/feedback/${f.id}`} className="hover:underline">
                    “{f.text}”
                  </Link>
                </li>
              ))}
            </ul>
            {i.topic && (
              <Link to={`/feedback?topic=${i.topic.id}`} className="mt-2 inline-block text-xs font-medium text-accent-700">
                View all records for {i.topic.name}
              </Link>
            )}
          </div>
          <details className="text-xs text-muted">
            <summary className="cursor-pointer">Statistics</summary>
            <pre className="mt-2 overflow-x-auto rounded bg-slate-50 p-2">{JSON.stringify(i.statistics, null, 2)}</pre>
          </details>
        </div>
      )}
    </Dialog>
  );
}

export default function InsightsPage() {
  const ws = useWsKey();
  const qc = useQueryClient();
  const { can } = useAuth();
  const { filters } = useFilters();
  const [status, setStatus] = useState("active");
  const [sp, setSp] = useSearchParams();
  const openId = sp.get("id");
  const q = useQuery({ queryKey: [ws, "insights", status], queryFn: () => api<Insight[]>(`/api/v1/insights?status=${status}`) });
  const ai = useQuery({ queryKey: [ws, "ai-status"], queryFn: () => api<{ ai: { configured: boolean } }>("/api/v1/analysis/status") });
  const generate = useMutation({
    mutationFn: (withAI: boolean) =>
      api<{ insights: Insight[]; narrative_job: unknown }>("/api/v1/insights/generate", {
        method: "POST",
        body: { with_ai_narrative: withAI, date_from: filters.dateFrom || null, date_to: filters.dateTo || null },
      }),
    onSuccess: (r, withAI) => {
      toast.success(`${r.insights.length} insight${r.insights.length === 1 ? "" : "s"} generated${withAI && r.insights.length ? ". AI summaries will appear shortly." : ""}`);
      qc.invalidateQueries({ queryKey: [ws, "insights"] });
      if (withAI) setTimeout(() => qc.invalidateQueries({ queryKey: [ws, "insights"] }), 4000);
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const setInsightStatus = useMutation({
    mutationFn: ({ id, s }: { id: string; s: string }) => api(`/api/v1/insights/${id}`, { method: "PATCH", body: { status: s } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [ws, "insights"] }),
  });
  const items = q.data ?? [];
  return (
    <div>
      <PageHeader
        title="Customer insights"
        description="Actionable findings supported by your feedback records. Rules require minimum sample sizes and significance tests."
        actions={
          can("insights:manage") && (
            <>
              <Button size="sm" variant="outline" loading={generate.isPending && generate.variables === false} onClick={() => generate.mutate(false)}>
                <Lightbulb className="h-3.5 w-3.5" /> Generate insights
              </Button>
              <Button size="sm" disabled={!ai.data?.ai.configured} title={ai.data?.ai.configured ? undefined : "Configure an AI provider first"} loading={generate.isPending && generate.variables === true} onClick={() => generate.mutate(true)}>
                <Sparkles className="h-3.5 w-3.5" /> Generate with AI summaries
              </Button>
            </>
          )
        }
      />
      <Notice tone="blue" className="mb-4">
        Insights use {filters.dateFrom ? `the selected range (${filters.dateFrom} – ${filters.dateTo || "today"})` : "the last 30 days of data"} compared with the previous period of equal length. Facts come from the database; AI (when enabled) only writes clearly labelled summaries.
      </Notice>
      <div className="mb-4 max-w-xs">
        <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="active">Active</option>
          <option value="resolved">Resolved</option>
          <option value="dismissed">Dismissed</option>
          <option value="all">All</option>
        </Select>
      </div>
      {q.isLoading && <LoadingBlock rows={6} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {q.data && items.length === 0 && (
        <EmptyState
          icon={<Lightbulb className="h-5 w-5" />}
          title="No insights"
          description="Generate insights to find recurring issues, rising complaints, product hotspots and what customers value. Small samples never produce insights."
        />
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {items.map((i) => (
          <Card key={i.id}>
            <div className="flex flex-wrap gap-1.5">
              <Badge tone="navy">{INSIGHT_KINDS[i.kind] ?? i.kind}</Badge>
              <ImportanceBadge importance={i.importance} />
              <StrengthBadge strength={i.evidence_strength} n={i.supporting_count} />
              {i.ai_summary && <AIGeneratedBadge model={i.ai_model} />}
            </div>
            <h3 className="mt-3 text-[15px] font-semibold">{i.title}</h3>
            <p className="mt-1 text-sm text-muted">{i.ai_summary ?? i.description}</p>
            <p className="mt-2 text-sm">
              <span className="font-medium">Suggested action: </span>
              {i.ai_suggested_action ?? i.suggested_action}
              {i.ai_suggested_action && <span className="text-xs text-violet-700"> (AI-generated)</span>}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
              <TrendIcon dir={i.trend_direction} />
              <span>
                {formatDate(i.period_start)} – {formatDate(i.period_end)}
              </span>
              {i.topic && <span>Topic: {i.topic.name}</span>}
              {i.product && <span>Product: {i.product.name}</span>}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => setSp({ id: i.id })}>
                View evidence
              </Button>
              {can("insights:manage") && i.status === "active" && (
                <>
                  <Button size="sm" variant="ghost" onClick={() => setInsightStatus.mutate({ id: i.id, s: "resolved" })}>
                    <CheckCircle2 className="h-3.5 w-3.5" /> Resolve
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setInsightStatus.mutate({ id: i.id, s: "dismissed" })}>
                    <XCircle className="h-3.5 w-3.5" /> Dismiss
                  </Button>
                </>
              )}
            </div>
          </Card>
        ))}
      </div>
      {openId && <InsightDetail id={openId} onClose={() => setSp({})} />}
    </div>
  );
}
