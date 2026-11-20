import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { ConfirmButton } from "@/components/dialog";
import { Badge, Button, Card, ErrorState, Field, Input, LoadingBlock, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useProducts, useSources, useWsKey } from "@/lib/hooks";
import { ROLE_LABELS, titleCase } from "@/lib/labels";
import type { AIInfo, Workspace } from "@/lib/types";
import { cn, formatDateTime, timeAgo } from "@/lib/utils";

const TABS = [
  ["profile", "Profile"],
  ["workspace", "Workspace"],
  ["members", "Members"],
  ["workspaces", "All workspaces"],
  ["ai", "AI provider"],
  ["catalog", "Products & sources"],
  ["activity", "Activity log"],
] as const;

const TIMEZONES = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : ["UTC", "Europe/London", "Europe/Kyiv", "America/New_York"];

function ProfileTab() {
  const { me, refreshMe } = useAuth();
  const [name, setName] = useState(me?.full_name ?? "");
  const pwSchema = z
    .object({
      current_password: z.string().min(1, "Required"),
      new_password: z.string().min(10, "At least 10 characters").regex(/[A-Za-z]/, "Include a letter").regex(/\d/, "Include a number"),
      confirm: z.string(),
    })
    .refine((v) => v.new_password === v.confirm, { message: "Passwords do not match", path: ["confirm"] });
  const form = useForm<z.infer<typeof pwSchema>>({ resolver: zodResolver(pwSchema) });
  const { logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <Card title="Profile">
        <div className="space-y-4">
          <Field label="Email" htmlFor="p-email">
            <Input id="p-email" value={me?.email ?? ""} readOnly />
          </Field>
          <Field label="Full name" htmlFor="p-name">
            <Input id="p-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Button
            disabled={!name.trim()}
            onClick={async () => {
              try {
                await api("/api/v1/auth/me", { method: "PATCH", body: { full_name: name } });
                await refreshMe();
                toast.success("Profile updated");
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
          >
            Save profile
          </Button>
        </div>
      </Card>
      <Card title="Change password" description="You will be signed out everywhere after changing it.">
        <form
          className="space-y-4"
          noValidate
          onSubmit={form.handleSubmit(async (v) => {
            try {
              await api("/api/v1/auth/change-password", { method: "POST", body: { current_password: v.current_password, new_password: v.new_password } });
              toast.success("Password changed. Please sign in again.");
              await logout();
              navigate("/login");
            } catch (e) {
              toast.error((e as Error).message);
            }
          })}
        >
          <Field label="Current password" htmlFor="pw-cur" error={form.formState.errors.current_password?.message}>
            <Input id="pw-cur" type="password" autoComplete="current-password" {...form.register("current_password")} />
          </Field>
          <Field label="New password" htmlFor="pw-new" error={form.formState.errors.new_password?.message}>
            <Input id="pw-new" type="password" autoComplete="new-password" {...form.register("new_password")} />
          </Field>
          <Field label="Confirm new password" htmlFor="pw-conf" error={form.formState.errors.confirm?.message}>
            <Input id="pw-conf" type="password" autoComplete="new-password" {...form.register("confirm")} />
          </Field>
          <Button type="submit" loading={form.formState.isSubmitting}>
            Change password
          </Button>
        </form>
      </Card>
    </div>
  );
}

function WorkspaceTab() {
  const ws = useWsKey();
  const { can, refreshMe, workspace } = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: [ws, "workspace"], queryFn: () => api<Workspace>("/api/v1/workspace") });
  const [v, setV] = useState<Partial<Workspace>>({});
  const data = { ...q.data, ...v } as Workspace;
  const [confirmName, setConfirmName] = useState("");
  if (q.isLoading) return <LoadingBlock />;
  if (q.isError) return <ErrorState error={q.error} />;
  const editable = can("workspace:update");
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <Card title="Workspace details">
        <div className="space-y-4">
          <Field label="Name" htmlFor="w-name">
            <Input id="w-name" value={data.name} disabled={!editable} onChange={(e) => setV({ ...v, name: e.target.value })} />
          </Field>
          <Field label="Description" htmlFor="w-desc">
            <Textarea id="w-desc" rows={2} value={data.description} disabled={!editable} onChange={(e) => setV({ ...v, description: e.target.value })} />
          </Field>
          <Field label="Industry" htmlFor="w-ind">
            <Input id="w-ind" value={data.industry} disabled={!editable} onChange={(e) => setV({ ...v, industry: e.target.value })} />
          </Field>
          <Field label="Time zone" htmlFor="w-tz" hint="Used to interpret dates without a time zone and to group analytics by local day, week and month.">
            <Select id="w-tz" value={data.timezone} disabled={!editable} onChange={(e) => setV({ ...v, timezone: e.target.value })}>
              {TIMEZONES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </Field>
          {editable && (
            <Button
              onClick={async () => {
                try {
                  await api("/api/v1/workspace", { method: "PATCH", body: v });
                  setV({});
                  await refreshMe();
                  qc.invalidateQueries({ queryKey: [ws] });
                  toast.success("Workspace updated");
                } catch (e) {
                  toast.error((e as Error).message);
                }
              }}
            >
              Save changes
            </Button>
          )}
        </div>
      </Card>
      {can("workspace:delete") && (
        <Card title="Danger zone">
          <p className="text-sm text-muted">Deleting the workspace permanently removes all its feedback, analyses, reports and settings for every member.</p>
          <Field label={`Type "${workspace?.name}" to confirm`} htmlFor="w-del" className="mt-4">
            <Input id="w-del" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} />
          </Field>
          <ConfirmButton
            title="Delete workspace permanently?"
            description="All data in this workspace will be deleted for all members."
            confirmLabel="Delete workspace"
            onConfirm={async () => {
              try {
                await api("/api/v1/workspace/delete", { method: "POST", body: { confirm_name: confirmName } });
                toast.success("Workspace deleted");
                await refreshMe();
                qc.clear();
                navigate("/");
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
            trigger={(open) => (
              <Button variant="danger" className="mt-3" disabled={confirmName !== workspace?.name} onClick={open}>
                Delete workspace
              </Button>
            )}
          />
        </Card>
      )}
    </div>
  );
}

function MembersTab() {
  const ws = useWsKey();
  const qc = useQueryClient();
  const { can, workspace } = useAuth();
  const manage = can("members:manage");
  const members = useQuery({ queryKey: [ws, "members"], queryFn: () => api<{ id: string; email: string; full_name: string; role: string; joined_at: string; is_you: boolean }[]>("/api/v1/workspace/members") });
  const invites = useQuery({ queryKey: [ws, "invitations"], queryFn: () => api<{ id: string; email: string; role: string; expires_at: string }[]>("/api/v1/workspace/invitations"), enabled: manage });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [link, setLink] = useState<string | null>(null);
  const act = useMutation({
    mutationFn: ({ path, method, body }: { path: string; method: string; body?: unknown }) => api<{ invite_link?: string }>(path, { method, body }),
    onSuccess: (r) => {
      if (r?.invite_link) setLink(r.invite_link);
      qc.invalidateQueries({ queryKey: [ws, "members"] });
      qc.invalidateQueries({ queryKey: [ws, "invitations"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
      <Card title="Members" className="lg:col-span-2">
        {members.isLoading && <LoadingBlock />}
        <ul className="divide-y divide-line">
          {members.data?.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <div>
                <div className="text-sm font-medium">
                  {m.full_name} {m.is_you && <Badge tone="teal">You</Badge>}
                </div>
                <div className="text-xs text-muted">
                  {m.email} · joined {timeAgo(m.joined_at)}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {manage && !m.is_you ? (
                  <Select aria-label={`Role for ${m.email}`} value={m.role} className="h-8 w-36 py-1 text-[13px]" onChange={(e) => act.mutate({ path: `/api/v1/workspace/members/${m.id}`, method: "PATCH", body: { role: e.target.value } })}>
                    {(workspace?.role === "owner" ? ["owner", "admin", "analyst", "viewer"] : ["analyst", "viewer", ...(m.role === "admin" || m.role === "owner" ? [m.role] : [])]).map((r) => (
                      <option key={r} value={r}>
                        {ROLE_LABELS[r]}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Badge tone="slate">{ROLE_LABELS[m.role]}</Badge>
                )}
                {(manage || m.is_you) && (
                  <Button
                    size="icon"
                    variant="ghost"
                    aria-label={m.is_you ? "Leave workspace" : `Remove ${m.email}`}
                    onClick={() => window.confirm(m.is_you ? "Leave this workspace?" : `Remove ${m.email} from the workspace?`) && act.mutate({ path: `/api/v1/workspace/members/${m.id}`, method: "DELETE" })}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
        <div className="mt-4 rounded-lg bg-slate-50 p-3 text-xs text-muted">
          <strong>Roles:</strong> Viewer - read and download reports. Analyst - add, import, analyse and manage topics, insights, alerts and reports. Administrator - also delete records, manage members, integrations and AI settings. Owner - also delete the workspace.
        </div>
      </Card>
      {manage && (
        <Card title="Invite a team member">
          <div className="space-y-3">
            <Field label="Email" htmlFor="inv-email">
              <Input id="inv-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Role" htmlFor="inv-role">
              <Select id="inv-role" value={role} onChange={(e) => setRole(e.target.value)}>
                <option value="viewer">Viewer</option>
                <option value="analyst">Analyst</option>
                {workspace?.role === "owner" && <option value="admin">Administrator</option>}
              </Select>
            </Field>
            <Button disabled={!email.includes("@")} loading={act.isPending} onClick={() => act.mutate({ path: "/api/v1/workspace/invitations", method: "POST", body: { email, role } }, { onSuccess: () => setEmail("") })}>
              Create invitation
            </Button>
            {link && (
              <Notice tone="teal">
                <p className="mb-1">No email service is configured. Share this one-time link with the invitee securely:</p>
                <div className="flex gap-1">
                  <Input readOnly value={link} aria-label="Invitation link" className="text-xs" />
                  <Button size="icon" variant="outline" aria-label="Copy invitation link" onClick={() => navigator.clipboard?.writeText(link).then(() => toast.success("Copied"))}>
                    <Copy className="h-4 w-4" />
                  </Button>
                </div>
              </Notice>
            )}
            {invites.data && invites.data.length > 0 && (
              <div>
                <h3 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-muted">Pending invitations</h3>
                <ul className="space-y-1 text-sm">
                  {invites.data.map((i) => (
                    <li key={i.id} className="flex items-center justify-between gap-2">
                      <span className="truncate">
                        {i.email} <span className="text-xs text-muted">({ROLE_LABELS[i.role]})</span>
                      </span>
                      <Button size="sm" variant="ghost" onClick={() => act.mutate({ path: `/api/v1/workspace/invitations/${i.id}`, method: "DELETE" })}>
                        Revoke
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}

function WorkspacesTab() {
  const { me, workspace, switchWorkspace, refreshMe } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [tz, setTz] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <Card title="Your workspaces">
        {me?.workspaces.length === 0 && <Notice tone="amber">You are not a member of any workspace. Create one to get started.</Notice>}
        <ul className="divide-y divide-line">
          {me?.workspaces.map((w) => (
            <li key={w.id} className="flex items-center justify-between gap-2 py-2.5">
              <span className="text-sm font-medium">
                {w.name} <Badge tone="slate">{ROLE_LABELS[w.role]}</Badge>
              </span>
              {w.id === workspace?.id ? (
                <Badge tone="teal">Current</Badge>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    switchWorkspace(w.id);
                    navigate("/");
                  }}
                >
                  Switch
                </Button>
              )}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Create a workspace" description="Workspaces keep data completely separate - for example one per company, brand or client.">
        <div className="space-y-3">
          <Field label="Name" htmlFor="nw-name">
            <Input id="nw-name" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Time zone" htmlFor="nw-tz">
            <Select id="nw-tz" value={tz} onChange={(e) => setTz(e.target.value)}>
              {TIMEZONES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </Field>
          <Button
            disabled={!name.trim()}
            onClick={async () => {
              try {
                const w = await api<Workspace>("/api/v1/workspaces", { method: "POST", body: { name, timezone: tz } });
                await refreshMe();
                switchWorkspace(w.id);
                toast.success(`Workspace "${w.name}" created`);
                navigate("/");
              } catch (e) {
                toast.error((e as Error).message);
              }
            }}
          >
            Create workspace
          </Button>
        </div>
      </Card>
    </div>
  );
}

interface AISettings {
  workspace_provider: string;
  workspace_model: string;
  workspace_key_set: boolean;
  server_provider: string;
  effective: AIInfo;
  encryption_available: boolean;
  workspace_keys_allowed: boolean;
  daily_token_limit: number;
  tokens_used_24h: number;
  can_manage: boolean;
}

function AITab() {
  const ws = useWsKey();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: [ws, "ai-settings"], queryFn: () => api<AISettings>("/api/v1/workspace/ai-settings") });
  const [provider, setProvider] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<AISettings>("/api/v1/workspace/ai-settings", { method: "PUT", body }),
    onSuccess: (r) => {
      qc.setQueryData([ws, "ai-settings"], r);
      qc.invalidateQueries({ queryKey: [ws] });
      setKey("");
      toast.success("AI settings saved");
    },
    onError: (e) => toast.error((e as Error).message),
  });
  if (q.isLoading) return <LoadingBlock />;
  if (q.isError) return <ErrorState error={q.error} />;
  const s = q.data!;
  const p = provider ?? s.workspace_provider;
  const m = model ?? s.workspace_model;
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <Card title="Current status">
        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted">AI features</dt>
            <dd>{s.effective.configured ? <Badge tone="green">Available</Badge> : <Badge tone="amber">Unavailable</Badge>}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted">Provider / model</dt>
            <dd>{s.effective.configured ? `${s.effective.provider} · ${s.effective.model}` : "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted">Configured by</dt>
            <dd>{s.effective.source === "workspace" ? "This workspace" : "Server environment"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted">Tokens used (24 h)</dt>
            <dd>
              {s.tokens_used_24h.toLocaleString()}
              {s.daily_token_limit ? ` / ${s.daily_token_limit.toLocaleString()}` : ""}
            </dd>
          </div>
        </dl>
        {!s.effective.configured && s.effective.message && <Notice tone="amber" className="mt-4">{s.effective.message}</Notice>}
        <p className="mt-4 text-xs text-muted">Without AI, the rule-based analyser (English only) classifies sentiment and keyword rules assign topics. Everything is labelled with the method used.</p>
      </Card>
      <Card title="Workspace AI provider" description={s.can_manage ? "Override the server default for this workspace." : "Only administrators can change AI settings."}>
        <div className="space-y-4">
          <Field label="Provider" htmlFor="ai-p">
            <Select id="ai-p" value={p} disabled={!s.can_manage} onChange={(e) => setProvider(e.target.value)}>
              <option value="default">Server default ({s.server_provider})</option>
              <option value="none">Disabled for this workspace</option>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Google Gemini</option>
            </Select>
          </Field>
          {["anthropic", "openai", "gemini"].includes(p) && (
            <>
              <Field label="Model" htmlFor="ai-m" hint={p === "anthropic" ? "Leave empty for the default (claude-opus-5-5)." : "Enter the provider's model name."}>
                <Input id="ai-m" value={m} disabled={!s.can_manage} onChange={(e) => setModel(e.target.value)} />
              </Field>
              <Field label="API key" htmlFor="ai-k" hint={s.workspace_key_set ? "A key is stored (encrypted). Enter a new one to replace it." : s.encryption_available ? "Stored encrypted; never shown again. Leave empty to use the server's key." : "The server has no ENCRYPTION_KEY, so keys cannot be stored here."}>
                <Input id="ai-k" type="password" autoComplete="off" value={key} disabled={!s.can_manage || !s.encryption_available || !s.workspace_keys_allowed} onChange={(e) => setKey(e.target.value)} />
              </Field>
            </>
          )}
          {s.can_manage && (
            <div className="flex flex-wrap gap-2">
              <Button loading={save.isPending} onClick={() => save.mutate({ provider: p, model: m, ...(key ? { api_key: key } : {}) })}>
                Save
              </Button>
              {s.workspace_key_set && (
                <Button variant="outline" onClick={() => save.mutate({ provider: p, model: m, api_key: "" })}>
                  Remove stored key
                </Button>
              )}
            </div>
          )}
          <p className="text-xs text-muted">AI calls send only the feedback text needed for each task to the chosen provider. Costs depend on your provider account.</p>
        </div>
      </Card>
    </div>
  );
}

function CatalogTab() {
  const ws = useWsKey();
  const qc = useQueryClient();
  const { can } = useAuth();
  const products = useProducts();
  const sources = useSources();
  const [pName, setPName] = useState("");
  const [sName, setSName] = useState("");
  const [sKind, setSKind] = useState("review");
  const act = useMutation({
    mutationFn: ({ path, method, body }: { path: string; method: string; body?: unknown }) => api(path, { method, body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [ws, "products"] });
      qc.invalidateQueries({ queryKey: [ws, "sources"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
      <Card title="Products & services">
        <ul className="mb-3 divide-y divide-line">
          {products.data?.length === 0 && <li className="py-2 text-sm text-muted">No products yet. They are also created automatically by imports.</li>}
          {products.data?.map((p) => (
            <li key={p.id} className="flex items-center justify-between py-2 text-sm">
              <span>
                {p.name} <span className="text-xs text-muted">· {p.feedback_count} records</span>
              </span>
              {can("feedback:delete") && (
                <Button size="icon" variant="ghost" aria-label={`Delete product ${p.name}`} onClick={() => window.confirm(`Delete product "${p.name}"? Its feedback is kept without a product.`) && act.mutate({ path: `/api/v1/products/${p.id}`, method: "DELETE" })}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
        {can("feedback:write") && (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (pName.trim()) act.mutate({ path: "/api/v1/products", method: "POST", body: { name: pName } }, { onSuccess: () => setPName("") });
            }}
          >
            <Input aria-label="New product name" placeholder="New product" value={pName} onChange={(e) => setPName(e.target.value)} />
            <Button type="submit" size="sm">
              Add
            </Button>
          </form>
        )}
      </Card>
      <Card title="Feedback sources">
        <ul className="mb-3 divide-y divide-line">
          {sources.data?.map((s) => (
            <li key={s.id} className="flex items-center justify-between py-2 text-sm">
              <span>
                {s.name} <Badge tone="slate">{s.kind}</Badge> <span className="text-xs text-muted">· {s.feedback_count} records</span>
              </span>
              {can("feedback:delete") && (
                <Button size="icon" variant="ghost" aria-label={`Delete source ${s.name}`} onClick={() => window.confirm(`Delete source "${s.name}"? Its feedback is kept without a source.`) && act.mutate({ path: `/api/v1/sources/${s.id}`, method: "DELETE" })}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
        {can("feedback:write") && (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (sName.trim()) act.mutate({ path: "/api/v1/sources", method: "POST", body: { name: sName, kind: sKind } }, { onSuccess: () => setSName("") });
            }}
          >
            <Input aria-label="New source name" placeholder="New source" value={sName} onChange={(e) => setSName(e.target.value)} />
            <Select aria-label="Source type" value={sKind} onChange={(e) => setSKind(e.target.value)} className="w-36">
              {["review", "survey", "support", "social", "internal", "manual", "other"].map((k) => (
                <option key={k} value={k}>
                  {titleCase(k)}
                </option>
              ))}
            </Select>
            <Button type="submit" size="sm">
              Add
            </Button>
          </form>
        )}
      </Card>
    </div>
  );
}

function ActivityTab() {
  const ws = useWsKey();
  const q = useQuery({ queryKey: [ws, "activity"], queryFn: () => api<{ id: string; action: string; summary: string; user: string | null; created_at: string }[]>("/api/v1/workspace/activity?limit=200") });
  if (q.isLoading) return <LoadingBlock />;
  if (q.isError) return <ErrorState error={q.error} />;
  return (
    <Card title="Activity log" description="Audit trail of changes in this workspace">
      <div className="overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>When</th>
              <th>User</th>
              <th>Action</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.map((a) => (
              <tr key={a.id}>
                <td className="whitespace-nowrap text-muted">{formatDateTime(a.created_at)}</td>
                <td>{a.user ?? "System"}</td>
                <td>
                  <Badge tone="slate">{a.action}</Badge>
                </td>
                <td>{a.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export default function SettingsPage() {
  const [sp, setSp] = useSearchParams();
  const { me } = useAuth();
  const noWorkspace = me?.workspaces.length === 0;
  const tab = noWorkspace ? "workspaces" : sp.get("tab") ?? "profile";
  return (
    <div>
      <PageHeader title="Settings" />
      <div role="tablist" className="mb-5 flex flex-wrap gap-1 border-b border-line">
        {TABS.filter(([k]) => !noWorkspace || k === "workspaces" || k === "profile").map(([k, label]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setSp({ tab: k })}
            className={cn("-mb-px border-b-2 px-3 py-2 text-sm font-medium", tab === k ? "border-accent-600 text-ink" : "border-transparent text-muted hover:text-ink")}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "profile" && <ProfileTab />}
      {tab === "workspace" && <WorkspaceTab />}
      {tab === "members" && <MembersTab />}
      {tab === "workspaces" && <WorkspacesTab />}
      {tab === "ai" && <AITab />}
      {tab === "catalog" && <CatalogTab />}
      {tab === "activity" && <ActivityTab />}
    </div>
  );
}
