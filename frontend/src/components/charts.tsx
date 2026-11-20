import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { SENTIMENT_COLORS, SENTIMENTS, titleCase } from "@/lib/labels";
import type { Bucket, Distribution, TopicStat } from "@/lib/types";
import { EmptyState } from "./ui";

const axis = { fontSize: 11, fill: "#5b6478" };
const tooltipStyle = { borderRadius: 8, border: "1px solid #e3e7ef", fontSize: 12 };

function fmtBucket(b: string, granularity: string) {
  const d = new Date(`${b}T00:00:00`);
  if (granularity === "month") return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function SentimentDonut({ dist }: { dist: Distribution }) {
  const data = SENTIMENTS.map((s) => ({ name: titleCase(s), key: s, value: dist.counts[s] })).filter((d) => d.value > 0);
  if (!data.length) return <EmptyState title="No classified feedback" description="Sentiment appears once records are analysed." />;
  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <div className="h-44 w-44 shrink-0" role="img" aria-label="Sentiment distribution chart">
        <ResponsiveContainer>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius={48} outerRadius={78} paddingAngle={1.5} stroke="none">
              {data.map((d) => (
                <Cell key={d.key} fill={SENTIMENT_COLORS[d.key]} />
              ))}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="w-full space-y-1.5 text-sm">
        {SENTIMENTS.map((s) => (
          <li key={s} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SENTIMENT_COLORS[s] }} />
              {titleCase(s)}
            </span>
            <span className="tabular-nums text-muted">
              {dist.counts[s]} <span className="ml-1 inline-block w-12 text-right font-medium text-ink">{dist.percentages[s] ?? "—"}{dist.percentages[s] !== null ? "%" : ""}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SentimentOverTime({ buckets, granularity, height = 260 }: { buckets: Bucket[]; granularity: string; height?: number }) {
  if (!buckets.length || buckets.every((b) => b.total === 0)) return <EmptyState title="No data in this range" />;
  const data = buckets.map((b) => ({ ...b, label: fmtBucket(b.bucket, granularity) }));
  return (
    <div style={{ height }} role="img" aria-label="Sentiment over time chart">
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef1f6" vertical={false} />
          <XAxis dataKey="label" tick={axis} tickLine={false} axisLine={false} minTickGap={16} />
          <YAxis tick={axis} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip contentStyle={tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {SENTIMENTS.map((s) => (
            <Area key={s} type="monotone" dataKey={s} name={titleCase(s)} stackId="1" stroke={SENTIMENT_COLORS[s]} fill={SENTIMENT_COLORS[s]} fillOpacity={0.55} />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function NegativeShareLine({ buckets, granularity, height = 220 }: { buckets: Bucket[]; granularity: string; height?: number }) {
  const data = buckets.map((b) => ({ label: fmtBucket(b.bucket, granularity), negative: b.low_sample ? null : b.negative_share, total: b.total, avg: b.low_sample ? null : b.average_score }));
  if (!data.some((d) => d.negative !== null)) return <EmptyState title="Not enough data per period" description="Periods below the minimum sample size are not plotted." />;
  return (
    <div style={{ height }} role="img" aria-label="Negative share over time chart">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef1f6" vertical={false} />
          <XAxis dataKey="label" tick={axis} tickLine={false} axisLine={false} minTickGap={16} />
          <YAxis tick={axis} tickLine={false} axisLine={false} unit="%" domain={[0, 100]} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v) => (v === null ? "small sample" : `${v}%`)} />
          <Line type="monotone" dataKey="negative" name="Negative share" stroke={SENTIMENT_COLORS.negative} strokeWidth={2} dot={{ r: 2 }} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function VolumeBars({ buckets, granularity, height = 200 }: { buckets: Bucket[]; granularity: string; height?: number }) {
  if (!buckets.length) return <EmptyState title="No data in this range" />;
  const data = buckets.map((b) => ({ label: fmtBucket(b.bucket, granularity), total: b.total }));
  return (
    <div style={{ height }} role="img" aria-label="Feedback volume chart">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef1f6" vertical={false} />
          <XAxis dataKey="label" tick={axis} tickLine={false} axisLine={false} minTickGap={16} />
          <YAxis tick={axis} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip contentStyle={tooltipStyle} />
          <Bar dataKey="total" name="Records" fill="#22396a" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function TopicSentimentBars({ topics, height }: { topics: TopicStat[]; height?: number }) {
  if (!topics.length) return <EmptyState title="No topics yet" description="Topics are assigned by keyword rules, AI analysis or manually." />;
  const data = topics.map((t) => ({ name: t.name.length > 22 ? `${t.name.slice(0, 21)}…` : t.name, positive: t.positive, negative: t.negative, neutral: t.neutral, mixed: t.mixed, uncertain: t.uncertain }));
  return (
    <div style={{ height: height ?? Math.max(160, data.length * 30 + 40) }} role="img" aria-label="Topic sentiment comparison chart">
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eef1f6" horizontal={false} />
          <XAxis type="number" tick={axis} tickLine={false} axisLine={false} allowDecimals={false} />
          <YAxis type="category" dataKey="name" tick={axis} tickLine={false} axisLine={false} width={130} />
          <Tooltip contentStyle={tooltipStyle} />
          {SENTIMENTS.map((s) => (
            <Bar key={s} dataKey={s} name={titleCase(s)} stackId="a" fill={SENTIMENT_COLORS[s]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SimpleBars({ data, height = 220, color = "#0d9488", label = "Records" }: { data: { name: string; value: number }[]; height?: number; color?: string; label?: string }) {
  if (!data.length) return <EmptyState title="No data" />;
  return (
    <div style={{ height }} role="img" aria-label={`${label} chart`}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
          <XAxis type="number" tick={axis} tickLine={false} axisLine={false} allowDecimals={false} />
          <YAxis type="category" dataKey="name" tick={axis} tickLine={false} axisLine={false} width={130} />
          <Tooltip contentStyle={tooltipStyle} />
          <Bar dataKey="value" name={label} fill={color} radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
