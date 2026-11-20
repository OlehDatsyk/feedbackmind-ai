import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, GitCompareArrows } from "lucide-react";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, Card, Field, Input, Notice, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useProducts, useSources } from "@/lib/hooks";
import { fmtPct, fmtScore, SENTIMENTS, titleCase } from "@/lib/labels";
import type { Distribution } from "@/lib/types";

interface SegmentForm {
  label: string;
  date_from: string;
  date_to: string;
  product_id: string;
  source_id: string;
  segment: string;
}

interface TopicCompare {
  id: string;
  name: string;
  a_count: number;
  b_count: number;
  a_volume_share: number | null;
  b_volume_share: number | null;
  a_negative_share: number | null;
  b_negative_share: number | null;
  p_value: number | null;
  status: string;
}

interface CompareResult {
  a: { label: string; summary: Distribution };
  b: { label: string; summary: Distribution };
  negative_share_test: { p1: number; p2: number; p_value: number; significant: boolean; valid: boolean } | null;
  topics: TopicCompare[];
  improving: TopicCompare[];
  declining: TopicCompare[];
  emerging: TopicCompare[];
  warnings: string[];
  methodology: string;
  min_sample_size: number;
}

const EMPTY: SegmentForm = { label: "", date_from: "", date_to: "", product_id: "", source_id: "", segment: "" };

function SegmentEditor({ title, value, onChange }: { title: string; value: SegmentForm; onChange: (v: SegmentForm) => void }) {
  const products = useProducts().data ?? [];
  const sources = useSources().data ?? [];
  const id = title.replace(/\s/g, "");
  return (
    <Card title={title}>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Label" htmlFor={`${id}-label`} className="sm:col-span-2">
          <Input id={`${id}-label`} value={value.label} placeholder={title} onChange={(e) => onChange({ ...value, label: e.target.value })} />
        </Field>
        <Field label="From" htmlFor={`${id}-from`}>
          <Input id={`${id}-from`} type="date" value={value.date_from} onChange={(e) => onChange({ ...value, date_from: e.target.value })} />
        </Field>
        <Field label="To" htmlFor={`${id}-to`}>
          <Input id={`${id}-to`} type="date" value={value.date_to} onChange={(e) => onChange({ ...value, date_to: e.target.value })} />
        </Field>
        <Field label="Product" htmlFor={`${id}-prod`}>
          <Select id={`${id}-prod`} value={value.product_id} onChange={(e) => onChange({ ...value, product_id: e.target.value })}>
            <option value="">All products</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Source" htmlFor={`${id}-src`}>
          <Select id={`${id}-src`} value={value.source_id} onChange={(e) => onChange({ ...value, source_id: e.target.value })}>
            <option value="">All sources</option>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Customer segment" htmlFor={`${id}-seg`} hint="Exact value from the data" className="sm:col-span-2">
          <Input id={`${id}-seg`} value={value.segment} onChange={(e) => onChange({ ...value, segment: e.target.value })} />
        </Field>
      </div>
    </Card>
  );
}

function toBody(s: SegmentForm) {
  return {
    label: s.label,
    date_from: s.date_from || null,
    date_to: s.date_to || null,
    product_ids: s.product_id ? [s.product_id] : [],
    source_ids: s.source_id ? [s.source_id] : [],
    segment: s.segment || null,
  };
}

const STATUS_TONE: Record<string, "red" | "green" | "violet" | "slate"> = { declining: "red", improving: "green", emerging: "violet", no_significant_change: "slate", insufficient_data: "slate" };

export default function ComparisonsPage() {
  const [a, setA] = useState<SegmentForm>({ ...EMPTY, label: "Segment A" });
  const [b, setB] = useState<SegmentForm>({ ...EMPTY, label: "Segment B" });
  const run = useMutation({ mutationFn: () => api<CompareResult>("/api/v1/comparisons", { method: "POST", body: { a: toBody(a), b: toBody(b) } }) });
  const r = run.data;
  const chart = r ? SENTIMENTS.map((s) => ({ name: titleCase(s), [r.a.label]: r.a.summary.percentages[s] ?? 0, [r.b.label]: r.b.summary.percentages[s] ?? 0 })) : [];
  return (
    <div>
      <PageHeader title="Comparisons" description="Compare two date ranges, products, sources or customer segments. Segment A is the baseline." />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <SegmentEditor title="Segment A" value={a} onChange={setA} />
        <SegmentEditor title="Segment B" value={b} onChange={setB} />
      </div>
      <div className="mt-4">
        <Button onClick={() => run.mutate()} loading={run.isPending}>
          <GitCompareArrows className="h-4 w-4" /> Compare
        </Button>
      </div>
      {run.isError && (
        <Notice tone="red" className="mt-4">
          {(run.error as Error).message}
        </Notice>
      )}
      {r && (
        <div className="mt-6 space-y-5">
          {r.warnings.length > 0 && (
            <Notice tone="amber" icon={<AlertTriangle className="h-4 w-4" />}>
              <ul className="list-disc space-y-0.5 pl-4">
                {r.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </Notice>
          )}
          <div className="card overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>{r.a.label}</th>
                  <th>{r.b.label}</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Feedback volume</td>
                  <td>{r.a.summary.total}</td>
                  <td>{r.b.summary.total}</td>
                </tr>
                {SENTIMENTS.map((s) => (
                  <tr key={s}>
                    <td>{titleCase(s)} share</td>
                    <td>{fmtPct(r.a.summary.percentages[s])}</td>
                    <td>{fmtPct(r.b.summary.percentages[s])}</td>
                  </tr>
                ))}
                <tr>
                  <td>Average sentiment</td>
                  <td>{fmtScore(r.a.summary.average_score)}</td>
                  <td>{fmtScore(r.b.summary.average_score)}</td>
                </tr>
              </tbody>
            </table>
            {r.negative_share_test && (
              <p className="px-4 py-3 text-sm">
                Difference in negative share: {r.negative_share_test.significant ? <Badge tone="red">statistically significant</Badge> : <Badge tone="slate">not statistically significant</Badge>} (p = {r.negative_share_test.p_value.toFixed(4)})
                {!r.negative_share_test.valid && <span className="ml-1 text-xs text-amber-700">- sample too small for a reliable z-test</span>}
              </p>
            )}
          </div>
          <Card title="Sentiment distribution (% of classified)">
            <div className="h-64" role="img" aria-label="Sentiment distribution comparison chart">
              <ResponsiveContainer>
                <BarChart data={chart} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef1f6" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis unit="%" tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey={r.a.label} fill="#22396a" radius={[3, 3, 0, 0]} />
                  <Bar dataKey={r.b.label} fill="#0d9488" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
            {(["improving", "declining", "emerging"] as const).map((k) => (
              <Card key={k} title={`${titleCase(k)} topics`}>
                {r[k].length === 0 ? (
                  <p className="text-sm text-muted">None.</p>
                ) : (
                  <ul className="space-y-1 text-sm">
                    {r[k].map((t) => (
                      <li key={t.id}>
                        <strong>{t.name}</strong>: {fmtPct(t.a_negative_share)} → {fmtPct(t.b_negative_share)} negative
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            ))}
          </div>
          <Card title="Topic frequency">
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Topic</th>
                    <th>{r.a.label}: records (share)</th>
                    <th>{r.b.label}: records (share)</th>
                    <th>Negative share A → B</th>
                    <th>Assessment</th>
                  </tr>
                </thead>
                <tbody>
                  {r.topics.map((t) => (
                    <tr key={t.id}>
                      <td className="font-medium">{t.name}</td>
                      <td>
                        {t.a_count} ({fmtPct(t.a_volume_share)})
                      </td>
                      <td>
                        {t.b_count} ({fmtPct(t.b_volume_share)})
                      </td>
                      <td>
                        {fmtPct(t.a_negative_share)} → {fmtPct(t.b_negative_share)}
                      </td>
                      <td>
                        <Badge tone={STATUS_TONE[t.status] ?? "slate"}>{titleCase(t.status)}</Badge>
                        {t.p_value !== null && <span className="ml-1 text-xs text-muted">p = {t.p_value}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Notice tone="blue">
            <strong>Methodology.</strong> {r.methodology} Minimum sample size per topic: {r.min_sample_size}.
          </Notice>
        </div>
      )}
    </div>
  );
}
