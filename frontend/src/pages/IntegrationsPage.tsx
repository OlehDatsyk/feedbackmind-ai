import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Plug, RotateCw, Trash2, Webhook } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Dialog } from "@/components/dialog";
import { Badge, Button, Card, ErrorState, Field, Input, LoadingBlock, Notice, PageHeader, Select } from "@/components/ui";
import { API_BASE, api } from "@/lib/api";
import { useWsKey } from "@/lib/hooks";
import { formatDateTime } from "@/lib/utils";

interface CatalogItem {
  provider: string;
  name: string;
  status: "available" | "not_implemented";
  description: string;
  requirements: string[];
}

interface Configured {
  id: string;
  provider: "rest_api" | "webhook";
  name: string;
  status: "active" | "disabled";
  key_prefix: string | null;
  has_secret: boolean;
  records_received: number;
  last_used_at: string | null;
  created_at: string;
  endpoint: string;
}

interface IntegrationsResponse {
  catalog: CatalogItem[];
  configured: Configured[];
  encryption_available: boolean;
  can_manage: boolean;
}

function copy(text: string) {
  navigator.clipboard?.writeText(text).then(
    () => toast.success("Copied"),
    () => toast.error("Copy failed - select and copy manually"),
  );
}

export default function IntegrationsPage() {
  const ws = useWsKey();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: [ws, "integrations"], queryFn: () => api<IntegrationsResponse>("/api/v1/integrations") });
  const [createOpen, setCreateOpen] = useState(false);
  const [provider, setProvider] = useState<"rest_api" | "webhook">("rest_api");
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<{ kind: string; value: string; endpoint: string } | null>(null);
  const base = API_BASE || window.location.origin;

  const onSecret = (r: Configured & { api_key?: string; signing_secret?: string }) => {
    setSecret({ kind: r.api_key ? "API key" : "Signing secret", value: (r.api_key ?? r.signing_secret)!, endpoint: `${base}${r.endpoint}` });
    qc.invalidateQueries({ queryKey: [ws, "integrations"] });
  };
  const create = useMutation({
    mutationFn: () => api<Configured & { api_key?: string; signing_secret?: string }>("/api/v1/integrations", { method: "POST", body: { provider, name } }),
    onSuccess: (r) => {
      setCreateOpen(false);
      setName("");
      onSecret(r);
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const act = useMutation({
    mutationFn: ({ path, method, body }: { path: string; method: string; body?: unknown }) => api<Configured & { api_key?: string; signing_secret?: string }>(path, { method, body }),
    onSuccess: (r) => {
      if (r && (r.api_key || r.signing_secret)) onSecret(r);
      else qc.invalidateQueries({ queryKey: [ws, "integrations"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  if (q.isLoading) return <LoadingBlock rows={6} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data!;
  return (
    <div>
      <PageHeader
        title="Integrations"
        description="Bring feedback in automatically. Only integrations that actually work are offered; others show what they would require."
        actions={
          d.can_manage && (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plug className="h-3.5 w-3.5" /> New connection
            </Button>
          )
        }
      />
      {!d.can_manage && <Notice tone="blue" className="mb-4">Only workspace owners and administrators can manage integrations.</Notice>}
      <Card title="Active connections" className="mb-5">
        {d.configured.length === 0 ? (
          <p className="text-sm text-muted">No connections yet. Create a REST API key or a signed webhook.</p>
        ) : (
          <ul className="divide-y divide-line">
            {d.configured.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {c.provider === "rest_api" ? <KeyRound className="h-4 w-4 text-muted" /> : <Webhook className="h-4 w-4 text-muted" />}
                    <span className="font-medium">{c.name}</span>
                    <Badge tone={c.status === "active" ? "green" : "slate"}>{c.status}</Badge>
                  </div>
                  <p className="mt-1 break-all font-mono text-xs text-muted">
                    POST {base}
                    {c.endpoint}
                  </p>
                  <p className="text-xs text-muted">
                    {c.key_prefix && `Key ${c.key_prefix}… · `}
                    {c.records_received} records received · last used {c.last_used_at ? formatDateTime(c.last_used_at) : "never"}
                  </p>
                </div>
                {d.can_manage && (
                  <div className="flex gap-1.5">
                    <Button size="sm" variant="outline" onClick={() => act.mutate({ path: `/api/v1/integrations/${c.id}`, method: "PATCH", body: { status: c.status === "active" ? "disabled" : "active" } })}>
                      {c.status === "active" ? "Disable" : "Enable"}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => window.confirm("Rotate the credential? The old one stops working immediately.") && act.mutate({ path: `/api/v1/integrations/${c.id}/rotate`, method: "POST" })}>
                      <RotateCw className="h-3.5 w-3.5" /> Rotate
                    </Button>
                    <Button size="icon" variant="ghost" aria-label={`Delete ${c.name}`} onClick={() => window.confirm(`Delete "${c.name}"? Imported feedback is kept.`) && act.mutate({ path: `/api/v1/integrations/${c.id}`, method: "DELETE" })}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {d.catalog.map((c) => (
          <Card key={c.provider}>
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">{c.name}</h3>
              {c.status === "available" ? <Badge tone="green">Available</Badge> : <Badge tone="slate">Not available</Badge>}
            </div>
            <p className="mt-1 text-sm text-muted">{c.description}</p>
            <h4 className="mt-3 text-xs font-semibold uppercase tracking-wide text-muted">{c.status === "available" ? "Setup" : "Would require"}</h4>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-muted">
              {c.requirements.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            {c.status === "not_implemented" && <p className="mt-2 text-xs text-muted">No connector is included, so no connection is simulated. Use the REST API or webhook to push this data from your own systems.</p>}
          </Card>
        ))}
      </div>
      <Card title="Developer reference" className="mt-5">
        <div className="space-y-3 text-sm">
          <p>
            <strong>REST API:</strong> <code className="rounded bg-slate-100 px-1">POST /api/v1/ingest/feedback</code> with header <code className="rounded bg-slate-100 px-1">X-API-Key</code> and body{" "}
            <code className="rounded bg-slate-100 px-1">{'{"records": [{"text": "...", "received_at": "2026-01-01T10:00:00Z", "product": "...", "rating": 4, "external_id": "..."}]}'}</code> (max 100 per request).
          </p>
          <p>
            <strong>Webhook:</strong> send the same JSON (or a single record) to the webhook URL with headers <code className="rounded bg-slate-100 px-1">X-FeedbackMind-Timestamp</code> (Unix seconds) and{" "}
            <code className="rounded bg-slate-100 px-1">X-FeedbackMind-Signature: sha256=HMAC_SHA256(secret, timestamp + "." + raw_body)</code>. Requests older than 5 minutes are rejected.
          </p>
          <p className="text-muted">Duplicates (same external_id, or identical text/product/day/customer) are reported and skipped. Full API docs: /api/docs.</p>
        </div>
      </Card>

      <Dialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New connection"
        footer={
          <>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button loading={create.isPending} disabled={!name.trim()} onClick={() => create.mutate()}>
              Create
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Type" htmlFor="i-type">
            <Select id="i-type" value={provider} onChange={(e) => setProvider(e.target.value as "rest_api" | "webhook")}>
              <option value="rest_api">REST API key</option>
              <option value="webhook" disabled={!d.encryption_available}>
                Signed webhook{!d.encryption_available ? " (requires ENCRYPTION_KEY on the server)" : ""}
              </option>
            </Select>
          </Field>
          <Field label="Name" htmlFor="i-name" hint="e.g. Website widget, Helpdesk">
            <Input id="i-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        </div>
      </Dialog>
      <Dialog open={!!secret} onOpenChange={(o) => !o && setSecret(null)} title={`Your ${secret?.kind}`} description="Copy it now. For security it is stored hashed or encrypted and will never be shown again.">
        {secret && (
          <div className="space-y-3">
            <div className="flex gap-2">
              <Input readOnly value={secret.value} aria-label={secret.kind} className="font-mono text-xs" />
              <Button variant="outline" onClick={() => copy(secret.value)} aria-label="Copy secret">
                <Copy className="h-4 w-4" />
              </Button>
            </div>
            <p className="break-all text-xs text-muted">Endpoint: {secret.endpoint}</p>
          </div>
        )}
      </Dialog>
    </div>
  );
}
