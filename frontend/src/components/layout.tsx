import * as DM from "@radix-ui/react-dropdown-menu";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Bell,
  Bot,
  Building2,
  CalendarRange,
  ChevronDown,
  FileText,
  GitCompareArrows,
  LayoutDashboard,
  Lightbulb,
  LogOut,
  Menu,
  MessageSquareText,
  Plug,
  Settings,
  Siren,
  Tags,
  TriangleAlert,
  Upload,
  User,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { presetRange, useFilters, type DatePreset } from "@/lib/filters";
import { useWsKey } from "@/lib/hooks";
import { ROLE_LABELS } from "@/lib/labels";
import type { AlertEvent } from "@/lib/types";
import { cn, timeAgo } from "@/lib/utils";
import { Badge } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/feedback", label: "Feedback", icon: MessageSquareText },
  { to: "/imports", label: "Imports", icon: Upload },
  { to: "/topics", label: "Topics", icon: Tags },
  { to: "/insights", label: "Insights", icon: Lightbulb },
  { to: "/trends", label: "Trends", icon: BarChart3 },
  { to: "/analyst", label: "AI Analyst", icon: Bot },
  { to: "/alerts", label: "Alerts", icon: Siren },
  { to: "/comparisons", label: "Comparisons", icon: GitCompareArrows },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/integrations", label: "Integrations", icon: Plug },
  { to: "/settings", label: "Settings", icon: Settings },
];

/** Shown when the API runs as a temporary demo (EPHEMERAL_DEMO): its data is erased on restart or redeploy. */
export function StorageNotice() {
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ storage?: string }>("/health", { auth: false }),
    staleTime: 5 * 60_000,
    retry: false,
  });
  if (data?.storage !== "temporary") return null;
  return (
    <div role="status" className="flex items-start gap-2 bg-amber-100 px-4 py-2 text-sm text-amber-900 sm:px-6">
      <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>
        <strong>Temporary demo.</strong> Data on this deployment is erased whenever the server restarts or is redeployed. Do not upload real
        customer data.
      </span>
    </div>
  );
}

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <img src="/favicon.svg" alt="" className="h-8 w-8" />
      <div className="leading-tight">
        <div className="text-[15px] font-semibold text-white">FeedbackMind</div>
        <div className="text-[11px] font-medium tracking-wide text-accent-500">AI · Customer intelligence</div>
      </div>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-1 bg-navy-950 px-3 py-4">
      <div className="mb-5">
        <Logo />
      </div>
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn("flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors", isActive ? "bg-navy-800 text-white" : "text-slate-300 hover:bg-navy-900 hover:text-white")
          }
        >
          <Icon className="h-4 w-4 shrink-0" aria-hidden />
          {label}
        </NavLink>
      ))}
      <div className="mt-auto px-3 pt-4 text-[11px] text-slate-500">v1.0 · Figures come from your stored data.</div>
    </nav>
  );
}

function WorkspaceSelector() {
  const { me, workspace, switchWorkspace } = useAuth();
  const navigate = useNavigate();
  if (!workspace) return null;
  return (
    <DM.Root>
      <DM.Trigger className="flex min-w-0 items-center gap-2 rounded-lg border border-line bg-white px-2.5 py-1.5 text-sm hover:bg-slate-50" aria-label="Switch workspace">
        <Building2 className="h-4 w-4 shrink-0 text-muted" />
        <span className="max-w-[9rem] truncate font-medium sm:max-w-[14rem]">{workspace.name}</span>
        <ChevronDown className="h-3.5 w-3.5 text-muted" />
      </DM.Trigger>
      <DM.Portal>
        <DM.Content align="start" sideOffset={6} className="z-50 min-w-[16rem] rounded-lg border border-line bg-white p-1 shadow-lg">
          <DM.Label className="px-2 py-1.5 text-xs font-medium text-muted">Workspaces</DM.Label>
          {me?.workspaces.map((w) => (
            <DM.Item
              key={w.id}
              onSelect={() => {
                switchWorkspace(w.id);
                navigate("/");
              }}
              className={cn("flex cursor-pointer items-center justify-between gap-3 rounded-md px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-slate-100", w.id === workspace.id && "font-semibold")}
            >
              <span className="truncate">{w.name}</span>
              <Badge tone="slate">{ROLE_LABELS[w.role]}</Badge>
            </DM.Item>
          ))}
          <DM.Separator className="my-1 h-px bg-line" />
          <DM.Item onSelect={() => navigate("/settings?tab=workspaces")} className="cursor-pointer rounded-md px-2 py-1.5 text-sm text-accent-700 outline-none data-[highlighted]:bg-slate-100">
            + Create or manage workspaces
          </DM.Item>
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}

const PRESETS: { value: DatePreset; label: string }[] = [
  { value: "all", label: "All time" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "365d", label: "Last 12 months" },
  { value: "custom", label: "Custom range" },
];

function DateRangeSelector() {
  const { filters, setFilters } = useFilters();
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <CalendarRange className="hidden h-4 w-4 text-muted sm:block" aria-hidden />
      <label className="sr-only" htmlFor="date-preset">
        Date range
      </label>
      <select
        id="date-preset"
        value={filters.preset}
        onChange={(e) => {
          const preset = e.target.value as DatePreset;
          setFilters(preset === "custom" ? { preset } : { preset, ...presetRange(preset) });
        }}
        className="input h-8 w-auto py-1 pr-7 text-[13px]"
      >
        {PRESETS.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
      {filters.preset === "custom" && (
        <>
          <input aria-label="From date" type="date" className="input h-8 w-auto py-1 text-[13px]" value={filters.dateFrom} max={filters.dateTo || undefined} onChange={(e) => setFilters({ dateFrom: e.target.value })} />
          <span className="text-xs text-muted">to</span>
          <input aria-label="To date" type="date" className="input h-8 w-auto py-1 text-[13px]" value={filters.dateTo} min={filters.dateFrom || undefined} onChange={(e) => setFilters({ dateTo: e.target.value })} />
        </>
      )}
    </div>
  );
}

function Notifications() {
  const ws = useWsKey();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: [ws, "alert-events", "bell"], queryFn: () => api<{ unread: number; items: AlertEvent[] }>("/api/v1/alerts/events?limit=6"), refetchInterval: 60_000 });
  const unread = data?.unread ?? 0;
  return (
    <DM.Root>
      <DM.Trigger className="relative rounded-lg p-2 text-muted hover:bg-slate-100 hover:text-ink" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}>
        <Bell className="h-[18px] w-[18px]" />
        {unread > 0 && <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white">{unread > 9 ? "9+" : unread}</span>}
      </DM.Trigger>
      <DM.Portal>
        <DM.Content align="end" sideOffset={6} className="z-50 w-80 rounded-lg border border-line bg-white p-1 shadow-lg">
          <DM.Label className="px-2 py-1.5 text-xs font-medium text-muted">Alerts</DM.Label>
          {!data?.items.length && <p className="px-2 py-3 text-sm text-muted">No alerts yet. Configure alert rules on the Alerts page.</p>}
          {data?.items.map((e) => (
            <DM.Item key={e.id} onSelect={() => navigate(`/alerts?event=${e.id}`)} className="cursor-pointer rounded-md px-2 py-2 outline-none data-[highlighted]:bg-slate-100">
              <div className={cn("text-sm", !e.is_read && "font-semibold")}>{e.title}</div>
              <div className="text-xs text-muted">{timeAgo(e.triggered_at)}</div>
            </DM.Item>
          ))}
          <DM.Separator className="my-1 h-px bg-line" />
          <DM.Item onSelect={() => navigate("/alerts")} className="cursor-pointer rounded-md px-2 py-1.5 text-sm text-accent-700 outline-none data-[highlighted]:bg-slate-100">
            View all alerts
          </DM.Item>
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}

function UserMenu() {
  const { me, workspace, logout } = useAuth();
  const navigate = useNavigate();
  const initials = (me?.full_name || me?.email || "?")
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <DM.Root>
      <DM.Trigger className="flex h-8 w-8 items-center justify-center rounded-full bg-navy-900 text-xs font-semibold text-white" aria-label="Account menu">
        {initials}
      </DM.Trigger>
      <DM.Portal>
        <DM.Content align="end" sideOffset={6} className="z-50 min-w-[14rem] rounded-lg border border-line bg-white p-1 shadow-lg">
          <div className="px-2 py-2">
            <div className="text-sm font-medium">{me?.full_name}</div>
            <div className="truncate text-xs text-muted">{me?.email}</div>
            {workspace && <div className="mt-1 text-xs text-muted">Role: {ROLE_LABELS[workspace.role]}</div>}
          </div>
          <DM.Separator className="my-1 h-px bg-line" />
          <DM.Item onSelect={() => navigate("/settings")} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-slate-100">
            <User className="h-4 w-4" /> Profile & settings
          </DM.Item>
          <DM.Item
            onSelect={async () => {
              await logout();
              navigate("/login");
            }}
            className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-red-700 outline-none data-[highlighted]:bg-red-50"
          >
            <LogOut className="h-4 w-4" /> Sign out
          </DM.Item>
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}

export function AppLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);
  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 lg:block">
        <div className="fixed inset-y-0 w-60">
          <Sidebar />
        </div>
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-navy-950/50" onClick={() => setMobileOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-64">
            <Sidebar onNavigate={() => setMobileOpen(false)} />
            <button className="absolute right-2 top-3 rounded-md p-1.5 text-slate-300 hover:text-white" onClick={() => setMobileOpen(false)} aria-label="Close navigation">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <StorageNotice />
        <header className="sticky top-0 z-30 border-b border-line bg-white/95 backdrop-blur">
          <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 sm:px-6">
            <button className="rounded-md p-1.5 text-muted hover:bg-slate-100 lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
              <Menu className="h-5 w-5" />
            </button>
            <WorkspaceSelector />
            <div className="order-last w-full sm:order-none sm:ml-2 sm:w-auto">
              <DateRangeSelector />
            </div>
            <div className="ml-auto flex items-center gap-1.5">
              <Notifications />
              <UserMenu />
            </div>
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function AuthShell({ children, title, subtitle }: { children: ReactNode; title: string; subtitle?: ReactNode }) {
  return (
    <div className="flex min-h-full flex-col bg-navy-950">
      <StorageNotice />
      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-md">
          <div className="mb-6 flex justify-center">
            <Link to="/" aria-label="FeedbackMind AI home">
              <Logo />
            </Link>
          </div>
          <div className="rounded-2xl bg-white p-6 shadow-xl sm:p-8">
            <h1 className="text-xl font-semibold">{title}</h1>
            {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
            <div className="mt-6">{children}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
