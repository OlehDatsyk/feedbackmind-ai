import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { AIGeneratedBadge } from "@/components/badges";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, LoadingBlock, Notice, PageHeader, Select } from "@/components/ui";
import { api, downloadFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFilters } from "@/lib/filters";
import { useWsKey } from "@/lib/hooks";
import type { Report } from "@/lib/types";
import { formatBytes, formatDateTime } from "@/lib/utils";

const FORMATS = [
  { value: "pdf", label: "PDF report", hint: "Summary, topics, emerging problems, highlights, insights, evidence, actions, methodology" },
  { value: "docx", label: "Word (DOCX) report", hint: "Same content as the PDF, editable" },
  { value: "xlsx", label: "Excel workbook", hint: "Summary, topics, insights, all matching records, methodology" },
  { value: "csv", label: "CSV export", hint: "All matching records with their analysis" },
];

export default function ReportsPage() {
  const ws = useWsKey();
  const qc = useQueryClient();
  const { can } = useAuth();
  const { filters } = useFilters();
  const [format, setFormat] = useState("pdf");
  const [title, setTitle] = useState("Customer feedback report");
  const list = useQuery({
    queryKey: [ws, "reports"],
    queryFn: () => api<Report[]>("/api/v1/reports"),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 1500 : false),
  });
  const create = useMutation({
    mutationFn: () =>
      api<Report>("/api/v1/reports", {
        method: "POST",
        body: {
          title,
          format,
          filters: { date_from: filters.dateFrom || null, date_to: filters.dateTo || null, source_ids: filters.sourceIds, product_ids: filters.productIds, sentiments: filters.sentiments },
        },
      }),
    onSuccess: () => {
      toast.success("Report queued - it will be ready in a moment");
      qc.invalidateQueries({ queryKey: [ws, "reports"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`/api/v1/reports/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [ws, "reports"] }),
  });
  const scope = [filters.dateFrom || filters.dateTo ? `${filters.dateFrom || "earliest"} to ${filters.dateTo || "latest"}` : "all dates", filters.sourceIds.length ? `${filters.sourceIds.length} source(s)` : null, filters.productIds.length ? `${filters.productIds.length} product(s)` : null, filters.sentiments.length ? `sentiment: ${filters.sentiments.join(", ")}` : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <div>
      <PageHeader title="Reports & exports" description="Generated from real records for this workspace. AI-generated content is labelled in every report." />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {can("reports:create") ? (
          <Card title="New report" className="h-fit">
            <div className="space-y-4">
              <Field label="Title" htmlFor="r-title">
                <Input id="r-title" value={title} onChange={(e) => setTitle(e.target.value)} />
              </Field>
              <Field label="Format" htmlFor="r-format" hint={FORMATS.find((f) => f.value === format)?.hint}>
                <Select id="r-format" value={format} onChange={(e) => setFormat(e.target.value)}>
                  {FORMATS.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Notice tone="teal">Scope (from the current filters): {scope}. Archived records are excluded.</Notice>
              <Button className="w-full justify-center" loading={create.isPending} onClick={() => create.mutate()} disabled={!title.trim()}>
                <FileText className="h-4 w-4" /> Generate
              </Button>
            </div>
          </Card>
        ) : (
          <Notice tone="blue">Your role can download existing reports but not create new ones.</Notice>
        )}
        <Card title="Generated reports" className="lg:col-span-2">
          {list.isLoading && <LoadingBlock />}
          {list.isError && <ErrorState error={list.error} />}
          {list.data?.length === 0 && <EmptyState title="No reports yet" />}
          <ul className="divide-y divide-line">
            {list.data?.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{r.title}</span>
                    <Badge tone="navy">{r.format.toUpperCase()}</Badge>
                    {r.status === "ready" ? <Badge tone="green">Ready</Badge> : r.status === "failed" ? <Badge tone="red">Failed</Badge> : <Badge tone="blue">Generating…</Badge>}
                    {r.includes_ai && <AIGeneratedBadge />}
                  </div>
                  <p className="text-xs text-muted">
                    {formatDateTime(r.created_at)}
                    {r.record_count !== null && ` · ${r.record_count} records`}
                    {r.size_bytes !== null && ` · ${formatBytes(r.size_bytes)}`}
                    {r.error && ` · ${r.error}`}
                  </p>
                </div>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="outline" disabled={r.status !== "ready"} onClick={() => downloadFile(`/api/v1/reports/${r.id}/download`, r.file_name ?? `report.${r.format}`).catch((e) => toast.error((e as Error).message))}>
                    <Download className="h-3.5 w-3.5" /> Download
                  </Button>
                  {can("reports:create") && (
                    <Button size="icon" variant="ghost" aria-label={`Delete report ${r.title}`} onClick={() => del.mutate(r.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
