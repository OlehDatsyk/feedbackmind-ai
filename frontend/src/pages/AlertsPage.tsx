import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Plus, Play, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Dialog } from "@/components/dialog";
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, LoadingBlock, PageHeader, Select } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useProducts, useWsKey } from "@/lib/hooks";
import { titleCase } from "@/lib/labels";
import type { AlertEvent, AlertRule, TopicRow } from "@/lib/types";
import { cn, formatDateTime, timeAgo } from "@/lib/utils";

interface AlertType {
  key: string;
  label: string;
  threshold_label: string;
  default_threshold: number;
}

function RuleDialog({ open, onOpenChange, types, rule }: { open: boolean; onOpenChange: (o: boolean) => void; types: AlertType[]; rule: AlertRule | null }) {
  const ws = useWsKey();
  const qc = useQueryClient();
  const products = useProducts().data ?? [];
  const topics = useQuery({ queryKey: [ws, "topics-list"], queryFn: () => api<TopicRow[]>("/api/v1/topics") }).data ?? [];
  const [v, setV] = useState({
    name: rule?.name ?? "",
    alert_type: rule?.alert_type ?? types[0]?.key ?? "negative_spike",
    threshold: String(rule?.threshold ?? types[0]?.default_threshold ?? 50),
    window_days: String(rule?.window_days ?? 7),
    min_count: String(rule?.min_count ?? 5),
    cooldown_hours: String(rule?.cooldown_hours ?? 24),
    product_id: rule?.product_id ?? "",
    topic_id: rule?.topic_id ?? "",
  });
  const t = types.find((x) => x.key === v.alert_type);
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: v.name.trim() || t?.label,
        alert_type: v.alert_type,
        threshold: Number(v.threshold),
        window_days: Number(v.window_days),
        min_count: Number(v.min_count),
        cooldown_hours: Number(v.cooldown_hours),
        product_id: v.product_id || null,
        topic_id: v.topic_id || null,
      };
      return rule ? api(`/api/v1/alerts/rules/${rule.id}`, { method: "PATCH", body }) : api("/api/v1/alerts/rules", { method: "POST", body });
    },
    onSuccess: () => {
      toast.success("Alert rule saved");
      qc.invalidateQueries({ queryKey: [ws, "alert-rules"] });
      onOpenChange(false);
    },
    onError: (e) => toast.error((e as Error).message),
  });
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={rule ? "Edit alert rule" : "New alert rule"}
      description="An alert fires only when the condition is met, the minimum record count is reached and the rule is outside its cooldown."
      wide
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            Save rule
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Alert type" htmlFor="a-type">
          <Select id="a-type" value={v.alert_type} disabled={!!rule} onChange={(e) => setV({ ...v, alert_type: e.target.value, threshold: String(types.find((x) => x.key === e.target.value)?.default_threshold ?? 50) })}>
            {types.map((x) => (
              <option key={x.key} value={x.key}>
                {x.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Name" htmlFor="a-name">
          <Input id="a-name" value={v.name} placeholder={t?.label} onChange={(e) => setV({ ...v, name: e.target.value })} />
        </Field>
        {v.alert_type !== "new_topic" && (
          <Field label={t?.threshold_label ?? "Threshold"} htmlFor="a-thr">
            <Input id="a-thr" type="number" min={0} step="any" value={v.threshold} onChange={(e) => setV({ ...v, threshold: e.target.value })} />
          </Field>
        )}
        <Field label="Date window (days)" htmlFor="a-win" hint="Compared with the preceding window of equal length where relevant">
          <Input id="a-win" type="number" min={1} max={365} value={v.window_days} onChange={(e) => setV({ ...v, window_days: e.target.value })} />
        </Field>
        <Field label="Minimum records" htmlFor="a-min" hint="Prevents alerts from tiny samples">
          <Input id="a-min" type="number" min={1} value={v.min_count} onChange={(e) => setV({ ...v, min_count: e.target.value })} />
        </Field>
        <Field label="Cooldown (hours)" htmlFor="a-cool" hint="Avoids repeated notifications">
          <Input id="a-cool" type="number" min={0} value={v.cooldown_hours} onChange={(e) => setV({ ...v, cooldown_hours: e.target.value })} />
        </Field>
        <Field label={`Product${v.alert_type === "product_complaints" ? " *" : " (optional)"}`} htmlFor="a-prod">
          <Select id="a-prod" value={v.product_id} onChange={(e) => setV({ ...v, product_id: e.target.value })}>
            <option value="">All products</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Topic (optional)" htmlFor="a-topic">
          <Select id="a-topic" value={v.topic_id} onChange={(e) => setV({ ...v, topic_id: e.target.value })}>
            <option value="">All topics</option>
            {topics.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
    </Dialog>
  );
}

export default function AlertsPage() {
  const ws = useWsKey();
  const qc = useQueryClient();
  const { can } = useAuth();
  const manage = can("alerts:manage");
  const [sp] = useSearchParams();
  const focus = sp.get("event");
  const types = useQuery({ queryKey: [ws, "alert-types"], queryFn: () => api<AlertType[]>("/api/v1/alerts/types") });
  const rules = useQuery({ queryKey: [ws, "alert-rules"], queryFn: () => api<AlertRule[]>("/api/v1/alerts/rules") });
  const events = useQuery({ queryKey: [ws, "alert-events"], queryFn: () => api<{ unread: number; items: AlertEvent[] }>("/api/v1/alerts/events?limit=100") });
  const [dialog, setDialog] = useState<{ open: boolean; rule: AlertRule | null }>({ open: false, rule: null });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: [ws, "alert-rules"] });
    qc.invalidateQueries({ queryKey: [ws, "alert-events"] });
  };
  const act = useMutation({
    mutationFn: ({ path, method, body }: { path: string; method: string; body?: unknown }) => api<unknown>(path, { method, body }),
    onSuccess: invalidate,
    onError: (e) => toast.error((e as Error).message),
  });
  const evaluate = useMutation({
    mutationFn: () => api<{ triggered: AlertEvent[] }>("/api/v1/alerts/evaluate", { method: "POST" }),
    onSuccess: (r) => {
      toast.success(r.triggered.length ? `${r.triggered.length} alert(s) triggered` : "Rules evaluated - no conditions met");
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });
  useEffect(() => {
    if (focus) {
      const e = events.data?.items.find((x) => x.id === focus);
      if (e && !e.is_read) act.mutate({ path: `/api/v1/alerts/events/${e.id}`, method: "PATCH", body: { is_read: true } });
      document.getElementById(`event-${focus}`)?.scrollIntoView({ block: "center" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus, events.data]);

  return (
    <div>
      <PageHeader
        title="Smart alerts"
        description="Rules are evaluated automatically every 30 minutes and after each import. Each alert explains why it fired."
        actions={
          <>
            {manage && (
              <Button size="sm" variant="outline" loading={evaluate.isPending} onClick={() => evaluate.mutate()}>
                <Play className="h-3.5 w-3.5" /> Evaluate now
              </Button>
            )}
            {events.data && events.data.unread > 0 && (
              <Button size="sm" variant="outline" onClick={() => act.mutate({ path: "/api/v1/alerts/events/read-all", method: "POST" })}>
                Mark all read
              </Button>
            )}
            {manage && (
              <Button size="sm" onClick={() => setDialog({ open: true, rule: null })} disabled={!types.data}>
                <Plus className="h-3.5 w-3.5" /> New rule
              </Button>
            )}
          </>
        }
      />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-5">
        <Card title="Alert rules" className="xl:col-span-2">
          {rules.isLoading && <LoadingBlock />}
          {rules.isError && <ErrorState error={rules.error} />}
          {rules.data?.length === 0 && <EmptyState title="No alert rules" description="Create a rule to be notified about spikes, new topics or rising complaints." />}
          <ul className="divide-y divide-line">
            {rules.data?.map((r) => (
              <li key={r.id} className="flex items-start justify-between gap-3 py-3">
                <div className="min-w-0">
                  <button className="text-left text-sm font-medium hover:underline disabled:no-underline" disabled={!manage} onClick={() => setDialog({ open: true, rule: r })}>
                    {r.name}
                  </button>
                  <p className="text-xs text-muted">
                    {types.data?.find((t) => t.key === r.alert_type)?.label ?? titleCase(r.alert_type)} · threshold {r.threshold} · {r.window_days}d window · min {r.min_count}
                  </p>
                  <p className="text-xs text-muted">{r.last_triggered_at ? `Last triggered ${timeAgo(r.last_triggered_at)}` : "Never triggered"}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <label className="flex items-center gap-1.5 text-xs">
                    <input type="checkbox" className="h-4 w-4 accent-teal-600" checked={r.is_enabled} disabled={!manage} onChange={(e) => act.mutate({ path: `/api/v1/alerts/rules/${r.id}`, method: "PATCH", body: { is_enabled: e.target.checked } })} />
                    Enabled
                  </label>
                  {manage && (
                    <Button size="icon" variant="ghost" aria-label={`Delete rule ${r.name}`} onClick={() => window.confirm(`Delete rule "${r.name}"?`) && act.mutate({ path: `/api/v1/alerts/rules/${r.id}`, method: "DELETE" })}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Triggered alerts" className="xl:col-span-3">
          {events.isLoading && <LoadingBlock />}
          {events.data?.items.length === 0 && <EmptyState icon={<BellRing className="h-5 w-5" />} title="No alerts have fired" description="Alerts appear here when a rule's conditions are met." />}
          <ul className="space-y-3">
            {events.data?.items.map((e) => (
              <li key={e.id} id={`event-${e.id}`} className={cn("rounded-lg border p-3", e.id === focus ? "border-accent-600 ring-2 ring-accent-500/20" : "border-line", !e.is_read && "bg-amber-50/40")}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Badge tone={e.severity === "high" ? "red" : "amber"}>{titleCase(e.severity)}</Badge>
                    <span className="text-sm font-medium">{e.title}</span>
                  </div>
                  <span className="text-xs text-muted">{formatDateTime(e.triggered_at)}</span>
                </div>
                <p className="mt-2 text-sm text-muted">{e.explanation}</p>
                {e.evidence_ids.length > 0 && (
                  <p className="mt-2 flex flex-wrap gap-x-1.5 text-xs">
                    Supporting records:{" "}
                    {e.evidence_ids.map((id) => (
                      <Link key={id} to={`/feedback/${id}`} className="mr-1.5 font-mono text-accent-700 hover:underline">
                        #{id.slice(0, 8)}
                      </Link>
                    ))}
                  </p>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Badge tone={e.status === "open" ? "blue" : e.status === "resolved" ? "green" : "slate"}>{titleCase(e.status)}</Badge>
                  {manage && e.status !== "acknowledged" && e.status !== "resolved" && (
                    <Button size="sm" variant="ghost" onClick={() => act.mutate({ path: `/api/v1/alerts/events/${e.id}`, method: "PATCH", body: { status: "acknowledged", is_read: true } })}>
                      Acknowledge
                    </Button>
                  )}
                  {manage && e.status !== "resolved" && (
                    <Button size="sm" variant="ghost" onClick={() => act.mutate({ path: `/api/v1/alerts/events/${e.id}`, method: "PATCH", body: { status: "resolved", is_read: true } })}>
                      Resolve
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      {dialog.open && types.data && <RuleDialog open onOpenChange={(o) => setDialog({ open: o, rule: o ? dialog.rule : null })} types={types.data} rule={dialog.rule} />}
    </div>
  );
}
