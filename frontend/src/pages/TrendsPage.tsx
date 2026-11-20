import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { useState } from "react";
import { Line, LineChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { LowSampleBadge } from "@/components/badges";
import { NegativeShareLine, SentimentOverTime, VolumeBars } from "@/components/charts";
import { FilterBar } from "@/components/FilterBar";
import { Badge, Card, EmptyState, ErrorState, LoadingBlock, Notice, PageHeader, Select } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { useFilters } from "@/lib/filters";
import { useWsKey } from "@/lib/hooks";
import { fmtPct } from "@/lib/labels";
import type { Bucket, Series, StatTrend } from "@/lib/types";
import { TrendNote } from "./OverviewPage";

interface TopicChange {
  id: string;
  name: string;
  current_count: number;
  previous_count: number;
  current_negative_share: number | null;
  previous_negative_share: number | null;
  negative_share_test: { p_value: number; significant: boolean; diff: number } | null;
  is_new: boolean;
  low_sample: boolean;
}

interface TrendsResponse {
  observed: Series;
  statistical: { negative_share: StatTrend; volume: StatTrend; average_score: StatTrend };
  period_comparison: { current: [string, string]; topics: TopicChange[] };
  split: { id: string; name: string; series: Bucket[]; trend: StatTrend }[];
  notes: string[];
  min_sample_size: number;
}

const PALETTE = ["#0d9488", "#22396a", "#d97706", "#7c3aed", "#dc2626", "#0284c7"];

export default function TrendsPage() {
  const ws = useWsKey();
  const { params } = useFilters();
  const [granularity, setGranularity] = useState("");
  const [dimension, setDimension] = useState("topic");
  const p = { ...params, granularity: granularity || undefined, dimension };
  const q = useQuery({ queryKey: [ws, "trends", p], queryFn: () => api<TrendsResponse>(`/api/v1/trends${qs(p)}`) });
  const t = q.data;
  const splitData =
    t && t.split.length
      ? t.observed.buckets.map((b, i) => ({
          label: b.bucket,
          ...Object.fromEntries(t.split.map((s) => [s.name, s.series[i] && !s.series[i].low_sample ? s.series[i].negative_share : null])),
        }))
      : [];
  return (
    <div>
      <PageHeader title="Trends" description="How feedback changes over time - observed history, statistical trends and period comparisons." />
      <div className="mb-3 flex flex-wrap gap-2">
        <Select aria-label="Granularity" value={granularity} onChange={(e) => setGranularity(e.target.value)} className="w-40">
          <option value="">Automatic</option>
          <option value="day">Daily</option>
          <option value="week">Weekly</option>
          <option value="month">Monthly</option>
        </Select>
        <Select aria-label="Break down by" value={dimension} onChange={(e) => setDimension(e.target.value)} className="w-48">
          <option value="topic">Split by topic</option>
          <option value="product">Split by product</option>
          <option value="source">Split by source</option>
        </Select>
      </div>
      <FilterBar />
      {q.isLoading && <LoadingBlock rows={8} />}
      {q.isError && <ErrorState error={q.error} onRetry={() => q.refetch()} />}
      {t && t.observed.buckets.length === 0 && <EmptyState title="No data for trends" description="Add or import feedback to see trends." />}
      {t && t.observed.buckets.length > 0 && (
        <div className="space-y-5">
          <Notice tone="blue" icon={<Info className="h-4 w-4" />}>
            <ul className="list-disc space-y-0.5 pl-4">
              {t.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
              <li>Periods with fewer than {t.min_sample_size} records are flagged and excluded from statistical trends.</li>
            </ul>
          </Notice>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
            <Card title="Observed: sentiment over time" description={`Records per ${t.observed.granularity}`}>
              <SentimentOverTime buckets={t.observed.buckets} granularity={t.observed.granularity} />
            </Card>
            <Card title="Observed: feedback volume" actions={<TrendNote trend={t.statistical.volume} label="Volume" />}>
              <VolumeBars buckets={t.observed.buckets} granularity={t.observed.granularity} height={260} />
            </Card>
          </div>
          <Card title="Statistical: negative share" description="Line hidden for periods below the minimum sample size" actions={<TrendNote trend={t.statistical.negative_share} />}>
            <NegativeShareLine buckets={t.observed.buckets} granularity={t.observed.granularity} />
            {t.statistical.negative_share.status === "ok" && (
              <p className="mt-2 text-xs text-muted">
                Slope {t.statistical.negative_share.slope_per_bucket} percentage points per {t.observed.granularity}, R² {t.statistical.negative_share.r_squared}, p = {t.statistical.negative_share.p_value}. {t.statistical.negative_share.method}.
              </p>
            )}
          </Card>
          {t.split.length > 0 && (
            <Card title={`Negative share by ${dimension}`} description="Top groups by volume; gaps are periods below the minimum sample size">
              <div className="h-72" role="img" aria-label={`Negative share by ${dimension} chart`}>
                <ResponsiveContainer>
                  <LineChart data={splitData} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef1f6" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#5b6478" }} tickLine={false} axisLine={false} minTickGap={16} />
                    <YAxis unit="%" domain={[0, 100]} tick={{ fontSize: 11, fill: "#5b6478" }} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12 }} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    {t.split.map((s, i) => (
                      <Line key={s.id} type="monotone" dataKey={s.name} stroke={PALETTE[i % PALETTE.length]} strokeWidth={2} dot={false} connectNulls={false} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <ul className="mt-3 grid gap-1 text-xs text-muted sm:grid-cols-2">
                {t.split.map((s) => (
                  <li key={s.id}>
                    <strong className="text-ink">{s.name}:</strong> <TrendNote trend={s.trend} />
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <Card title="Period comparison by topic" description={`${t.period_comparison.current[0]} to ${t.period_comparison.current[1]} vs the preceding period of equal length (two-proportion z-test)`}>
            {t.period_comparison.topics.length === 0 ? (
              <p className="text-sm text-muted">No topics in these periods.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="table-base">
                  <thead>
                    <tr>
                      <th>Topic</th>
                      <th>Records (prev → now)</th>
                      <th>Negative share (prev → now)</th>
                      <th>Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {t.period_comparison.topics.map((c) => (
                      <tr key={c.id}>
                        <td className="font-medium">
                          {c.name} {c.low_sample && <LowSampleBadge />}
                        </td>
                        <td className="tabular-nums">
                          {c.previous_count} → {c.current_count}
                        </td>
                        <td className="tabular-nums">
                          {fmtPct(c.previous_negative_share)} → {fmtPct(c.current_negative_share)}
                        </td>
                        <td>
                          {c.is_new ? (
                            <Badge tone="violet">New topic</Badge>
                          ) : c.negative_share_test ? (
                            c.negative_share_test.significant ? (
                              <Badge tone={c.negative_share_test.diff > 0 ? "red" : "green"}>
                                {c.negative_share_test.diff > 0 ? "More negative" : "Less negative"} (p = {c.negative_share_test.p_value.toFixed(3)})
                              </Badge>
                            ) : (
                              <span className="text-xs text-muted">No significant change (p = {c.negative_share_test.p_value.toFixed(2)})</span>
                            )
                          ) : (
                            <span className="text-xs text-muted">Not enough data to test</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
