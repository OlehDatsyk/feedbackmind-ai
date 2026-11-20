import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, sessionStore, workspaceStore, type Session } from "./api";
import type { Me, WorkspaceRef } from "./types";

interface RegisterInput {
  email: string;
  password: string;
  full_name: string;
  workspace_name?: string;
  invitation_token?: string;
}

interface AuthValue {
  me: Me | undefined;
  workspace: WorkspaceRef | undefined;
  isAuthenticated: boolean;
  isLoading: boolean;
  can: (permission: string) => boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: RegisterInput) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<unknown>;
  switchWorkspace: (id: string) => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [hasSession, setHasSession] = useState(() => sessionStore.get() !== null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(() => workspaceStore.get());

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Me>("/api/v1/auth/me"),
    enabled: hasSession,
    staleTime: 60_000,
    retry: false,
  });

  useEffect(() => {
    const onLogout = () => {
      setHasSession(false);
      qc.clear();
    };
    window.addEventListener("fm:logout", onLogout);
    return () => window.removeEventListener("fm:logout", onLogout);
  }, [qc]);

  const workspaces = meQuery.data?.workspaces;
  const workspace = useMemo(() => {
    if (!workspaces?.length) return undefined;
    const ws = workspaces.find((w) => w.id === workspaceId) ?? workspaces[0];
    // Written synchronously (idempotent) so that the very first request from any child component already carries
    // the right X-Workspace-ID header - child effects run before this provider's effects would.
    if (ws.id !== workspaceStore.get()) workspaceStore.set(ws.id);
    return ws;
  }, [workspaces, workspaceId]);

  useEffect(() => {
    if (workspace && workspace.id !== workspaceId) setWorkspaceId(workspace.id);
  }, [workspace, workspaceId]);

  const start = useCallback(
    (s: Session) => {
      sessionStore.set(s);
      qc.clear();
      setHasSession(true);
    },
    [qc],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      start(await api<Session>("/api/v1/auth/login", { method: "POST", body: { email, password }, auth: false }));
    },
    [start],
  );

  const register = useCallback(
    async (input: RegisterInput) => {
      start(await api<Session>("/api/v1/auth/register", { method: "POST", body: input, auth: false }));
    },
    [start],
  );

  const logout = useCallback(async () => {
    const s = sessionStore.get();
    if (s) {
      try {
        await api("/api/v1/auth/logout", { method: "POST", body: { refresh_token: s.refresh_token }, auth: false });
      } catch {
        /* best effort */
      }
    }
    sessionStore.clear();
    setHasSession(false);
    qc.clear();
  }, [qc]);

  const switchWorkspace = useCallback(
    (id: string) => {
      workspaceStore.set(id);
      setWorkspaceId(id);
      // Drop every cached query so no data from the previous workspace is shown.
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
    [qc],
  );

  const value = useMemo<AuthValue>(
    () => ({
      me: meQuery.data,
      workspace,
      isAuthenticated: hasSession && !!meQuery.data,
      isLoading: hasSession && meQuery.isLoading,
      can: (p: string) => !!workspace?.permissions.includes(p),
      login,
      register,
      logout,
      refreshMe: () => meQuery.refetch(),
      switchWorkspace,
    }),
    [hasSession, meQuery, workspace, login, register, logout, switchWorkspace],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
