import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowDownRight, ArrowUpRight, Bot, FlaskConical, Gauge, MessageSquareText, Minus, Plus, Siren, ThumbsDown, ThumbsUp, Upload } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { DemoBadge, ImportanceBadge, LowSampleBadge, StrengthBadge } from "@/components/badges";
import { SentimentDonut, SentimentOverTime, SimpleBars, TopicSentimentBars } from "@/components/charts";
import { FilterBar } from "@/components/FilterBar";
import { Badge, Button, Card, EmptyState, ErrorState, LoadingBlock, Notice, PageHeader, Stat } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFilters } from "@/lib/filters";
import { useWsKey } from "@/lib/hooks";
import { fmtPct, fmtScore, titleCase } from "@/lib/labels";
import type { Overview, StatTrend } from "@/lib/types";
import { timeAgo } from "@/lib/utils";

export function TrendNote({ trend, label = "Negative share" }: { trend: StatTrend; label?: string }) {
  if (trend.status !== "ok") return <span className="text-xs text-muted">{label} trend: not enough data ({trend.note})</span>;
  const Icon = trend.direction === "up" ? ArrowUpRight : trend.direction === "down" ? ArrowDownRight : Minus;
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted" title={trend.method}>
      <Icon className="h-3.5 w-3.5" />
      {label} trend: {trend.significant ? `${trend.direction === "up" ? "rising" : "falling"} (p = ${trend.p_value})` : "no statistically significant change"} · {trend.points_used} periods
    </span>
  );
}

function DemoControls({ count }: { count: number }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const load = useMutation({
    mutationFn: () => api<{ demo_records: number }>("/api/v1/workspace/demo", { method: "POST" }),
    onSuccess: (r) => {
      toast.success(`Loaded ${r.demo_records} synthetic demo records`);
      qc.invalidateQueries();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: () => api<{ removed: number }>("/api/v1/workspace/demo", { method: "DELETE" }),
    onSuccess: (r) => {
      toast.success(`Removed ${r.removed} demo records`);
      qc.invalidateQueries();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  if (!can("demo:manage")) return null;
  return count > 0 ? (
    <Button variant="outline" size="sm" loading={remove.isPending} onClick={() => remove.mutate()}>
      Remove demo data
    </Button>
  ) : (
    <Button variant="outline" size="sm" loading={load.isPending} onClick={() => load.mutate()}>
      <FlaskConical className="h-3.5 w-3.5" /> Load sample dataset
    </Button>
  );
}

export function OverviewPage() {
  const ws = useWsKey();
  const { params } = useFilters();
  const { can } = useAuth();
  const q = useQuery({ queryKey: [ws, "overview", params], queryFn: () => api<Overview>(`/api/v1/analytics/overview${qs(params)}`) });
  const o = q.data;
  const d = o?.distribution;

  return (
    <div>
      <PageHeader
        title="Overview"
        description="All figures are computed from feedback stored in this workspace for the selected filters."
        actions={
          <>
            {o && <DemoControls count={o.demo_records} />}
            {can("feedback:write") && (
              <Link to="/feedback?new=1">
                <Button size="sm">
                  <Plus className="h-3.5 w-3.5" /> Add feedback
                </Button>
              </Link>
            )}
          </>
        }
      />
      <FilterBar />
      {q.isLoading && <LoadingBlock rows={8} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {o && d && (
        <div className="space-y-5">
          {o.demo_records > 0 && (
            <Notice tone="amber" icon={<FlaskConical className="h-4 w-4" />}>
              This workspace contains <strong>{o.demo_records} synthetic demo records</strong> (marked <DemoBadge />). They are not real customer feedback. Remove them before analysing real data.
            </Notice>
          )}
          {!o.ai.configured && (
            <Notice tone="blue" icon={<Bot className="h-4 w-4" />}>
              AI analysis is not configured, so sentiment shown here comes from the built-in rule-based analyser (English only, not AI). Statistics, imports and reports work normally.{" "}
              {can("ai_settings:manage") && (
                <Link to="/settings?tab=ai" className="font-medium underline">
                  Configure an AI provider
                </Link>
              )}
            </Notice>
          )}
          {d.total === 0 ? (
            <EmptyState
              icon={<MessageSquareText className="h-5 w-5" />}
              title={o.data_range.earliest ? "No feedback matches these filters" : "No feedback yet"}
              description={
                o.data_range.earliest
                  ? `Your data covers ${o.data_range.earliest} to ${o.data_range.latest}. Adjust the date range or filters.`
                  : "Import a CSV or Excel file, add feedback manually, connect an integration, or load the clearly labelled sample dataset to explore the product."
              }
              action={
                !o.data_range.earliest && (
                  <div className="flex flex-wrap justify-center gap-2">
                    {can("imports:manage") && (
                      <Link to="/imports">
                        <Button size="sm">
                          <Upload className="h-3.5 w-3.5" /> Import data
                        </Button>
                      </Link>
                    )}
                    <DemoControls count={0} />
                  </div>
                )
              }
            />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
                <Stat label="Feedback records" value={d.total.toLocaleString()} hint={`${d.classified} classified · ${d.unclassified} unclassified`} icon={<MessageSquareText className="h-4 w-4" />} />
                <Stat label="Positive" value={fmtPct(d.percentages.positive)} hint={`${d.counts.positive} records`} icon={<ThumbsUp className="h-4 w-4" />} />
                <Stat label="Negative" value={fmtPct(d.percentages.negative)} hint={`${d.counts.negative} records`} icon={<ThumbsDown className="h-4 w-4" />} />
                <Stat label="Neutral" value={fmtPct(d.percentages.neutral)} hint={`${d.counts.mixed} mixed · ${d.counts.uncertain} uncertain`} icon={<Minus className="h-4 w-4" />} />
                <Stat label="Average sentiment" value={fmtScore(d.average_score)} hint={`Scale -1 to +1 · ${d.average_score_n} scored`} icon={<Gauge className="h-4 w-4" />} />
              </div>
              <p className="text-xs text-muted">
                {d.denominator_note} Methods: {d.methods.ai} AI · {d.methods.lexicon} rule-based · {d.methods.manual} manual.
              </p>
              <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
                <Card title="Sentiment distribution" className="xl:col-span-1">
                  <SentimentDonut dist={d} />
                </Card>
                <Card title="Customer satisfaction over time" description={`Records per ${o.timeseries.granularity}, by sentiment`} className="xl:col-span-2" actions={<TrendNote trend={o.trend} />}>
                  <SentimentOverTime buckets={o.timeseries.buckets} granularity={o.timeseries.granularity} />
                </Card>
              </div>
              <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
                <Card title="Most common topics" description="Aspect-level sentiment where available" className="xl:col-span-2" actions={<Link to="/topics" className="text-xs font-medium text-accent-700">Manage topics</Link>}>
                  <TopicSentimentBars topics={o.topics} />
                </Card>
                <Card title="Newly detected issues" description={o.emerging_period ? `${o.emerging_period.from} to ${o.emerging_period.to} vs previous period` : undefined}>
                  {o.emerging.length === 0 ? (
                    <p className="text-sm text-muted">No new or statistically significant rising issues in this period.</p>
                  ) : (
                    <ul className="space-y-3">
                      {o.emerging.map((e) => (
                        <li key={e.id} className="text-sm">
                          <div className="flex items-center justify-between gap-2">
                            <Link to={`/feedback?topic=${e.id}`} className="font-medium hover:underline">
                              {e.name}
                            </Link>
                            {e.is_new ? <Badge tone="violet">New</Badge> : <Badge tone="red">Rising</Badge>}
                          </div>
                          <div className="text-xs text-muted">
                            {e.current_count} records (prev. {e.previous_count}) · negative {fmtPct(e.previous_negative_share)} → {fmtPct(e.current_negative_share)}
                            {e.p_value !== null && ` · p = ${e.p_value}`}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
              <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
                <Card title="Feedback by source">
                  <SimpleBars data={o.by_source.map((s) => ({ name: s.name, value: s.count }))} height={Math.max(140, o.by_source.length * 30 + 30)} color="#22396a" />
                </Card>
                <Card title="Feedback by product">
                  {o.by_product.length ? (
                    <ul className="divide-y divide-line text-sm">
                      {o.by_product.slice(0, 8).map((p) => (
                        <li key={p.id ?? "none"} className="flex items-center justify-between gap-2 py-2">
                          <span className="truncate">{p.name}</span>
                          <span className="flex shrink-0 items-center gap-2 text-xs text-muted">
                            {p.count} · {fmtPct(p.negative_share)} neg.
                            {p.low_sample && <LowSampleBadge />}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted">No products yet.</p>
                  )}
                </Card>
                <Card title="Emotions in wording" description="Text cues, not psychological assessments">
                  <SimpleBars data={o.emotions.map((e) => ({ name: titleCase(e.emotion), value: e.count }))} height={Math.max(140, o.emotions.length * 28 + 30)} color="#7c3aed" />
                </Card>
              </div>
            </>
          )}
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
            <Card title="Latest insights" actions={<Link to="/insights" className="text-xs font-medium text-accent-700">All insights</Link>}>
              {o.insights.length === 0 ? (
                <p className="text-sm text-muted">No insights yet. Generate them on the Insights page.</p>
              ) : (
                <ul className="space-y-3">
                  {o.insights.map((i) => (
                    <li key={i.id}>
                      <Link to={`/insights?id=${i.id}`} className="text-sm font-medium hover:underline">
                        {i.title}
                      </Link>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        <ImportanceBadge importance={i.importance} />
                        <StrengthBadge strength={i.evidence_strength} n={i.supporting_count} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Important alerts" actions={<Link to="/alerts" className="text-xs font-medium text-accent-700">Alerts</Link>}>
              {o.alerts.length === 0 ? (
                <p className="text-sm text-muted">No open alerts.</p>
              ) : (
                <ul className="space-y-3">
                  {o.alerts.map((a) => (
                    <li key={a.id} className="flex gap-2 text-sm">
                      <Siren className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
                      <div>
                        <Link to={`/alerts?event=${a.id}`} className="font-medium hover:underline">
                          {a.title}
                        </Link>
                        <div className="text-xs text-muted">{timeAgo(a.triggered_at)}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Recent activity">
              {o.activity.length === 0 ? (
                <p className="text-sm text-muted">No activity yet.</p>
              ) : (
                <ul className="space-y-2.5">
                  {o.activity.map((a) => (
                    <li key={a.id} className="flex gap-2 text-sm">
                      <Activity className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
                      <div className="min-w-0">
                        <div className="truncate">{a.summary || titleCase(a.action)}</div>
                        <div className="text-xs text-muted">
                          {a.user ?? "System"} · {timeAgo(a.created_at)}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
