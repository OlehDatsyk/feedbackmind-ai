import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useLocation, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { AuthShell } from "@/components/layout";
import { Button, Field, Input, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});

const passwordRule = z
  .string()
  .min(10, "At least 10 characters")
  .max(128)
  .regex(/[A-Za-z]/, "Include a letter")
  .regex(/\d/, "Include a number");

const registerSchema = z.object({
  full_name: z.string().trim().min(1, "Enter your name").max(200),
  email: z.string().email("Enter a valid email address"),
  workspace_name: z.string().max(200).optional(),
  password: passwordRule,
});

export function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) });
  if (isAuthenticated) return <Navigate to="/" replace />;
  const onSubmit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await login(v.email, v.password);
      navigate((location.state as { from?: string } | null)?.from ?? "/", { replace: true });
    } catch (e) {
      setError((e as Error).message);
    }
  });
  return (
    <AuthShell title="Sign in" subtitle="Customer feedback intelligence for your team.">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {error && <Notice tone="red">{error}</Notice>}
        <Field label="Email" htmlFor="email" error={form.formState.errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" {...form.register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" error={form.formState.errors.password?.message}>
          <Input id="password" type="password" autoComplete="current-password" {...form.register("password")} />
        </Field>
        <Button type="submit" className="w-full justify-center" loading={form.formState.isSubmitting}>
          Sign in
        </Button>
        <p className="text-center text-sm text-muted">
          New to FeedbackMind?{" "}
          <Link to="/register" className="font-medium text-accent-700 hover:underline">
            Create an account
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}

export function RegisterPage({ invitationToken, invitedEmail }: { invitationToken?: string; invitedEmail?: string }) {
  const { register: signUp, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof registerSchema>>({ resolver: zodResolver(registerSchema), defaultValues: { email: invitedEmail ?? "" } });
  if (isAuthenticated && !invitationToken) return <Navigate to="/" replace />;
  const onSubmit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await signUp({ ...v, workspace_name: v.workspace_name || undefined, invitation_token: invitationToken });
      toast.success("Welcome to FeedbackMind AI");
      navigate("/", { replace: true });
    } catch (e) {
      setError((e as Error).message);
    }
  });
  return (
    <AuthShell title={invitationToken ? "Join your team" : "Create your account"} subtitle={invitationToken ? "Create an account to accept the invitation." : "You will be the owner of a new workspace."}>
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {error && <Notice tone="red">{error}</Notice>}
        <Field label="Full name" htmlFor="full_name" error={form.formState.errors.full_name?.message}>
          <Input id="full_name" autoComplete="name" {...form.register("full_name")} />
        </Field>
        <Field label="Work email" htmlFor="email" error={form.formState.errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" readOnly={!!invitedEmail} {...form.register("email")} />
        </Field>
        {!invitationToken && (
          <Field label="Workspace name" htmlFor="workspace_name" hint="Usually your company or team name. You can change it later.">
            <Input id="workspace_name" {...form.register("workspace_name")} />
          </Field>
        )}
        <Field label="Password" htmlFor="password" error={form.formState.errors.password?.message} hint="At least 10 characters with a letter and a number.">
          <Input id="password" type="password" autoComplete="new-password" {...form.register("password")} />
        </Field>
        <Button type="submit" className="w-full justify-center" loading={form.formState.isSubmitting}>
          Create account
        </Button>
        <p className="text-center text-sm text-muted">
          Already have an account?{" "}
          <Link to="/login" className="font-medium text-accent-700 hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </AuthShell>
  );
}

export function AcceptInvitePage() {
  const { token = "" } = useParams();
  const { isAuthenticated, me, refreshMe, switchWorkspace } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const preview = useQuery({
    queryKey: ["invite", token],
    queryFn: () => api<{ workspace_name: string; email: string; role: string }>(`/api/v1/invitations/${encodeURIComponent(token)}`, { auth: false }),
    retry: false,
  });
  if (preview.isLoading) return <AuthShell title="Checking invitation…">Loading…</AuthShell>;
  if (preview.isError || !preview.data)
    return (
      <AuthShell title="Invitation unavailable">
        <Notice tone="red">This invitation is invalid, expired or has already been used. Ask your workspace administrator for a new one.</Notice>
      </AuthShell>
    );
  const inv = preview.data;
  if (!isAuthenticated) {
    return <RegisterPage invitationToken={token} invitedEmail={inv.email} />;
  }
  return (
    <AuthShell title={`Join ${inv.workspace_name}`} subtitle={`You were invited as ${inv.role}.`}>
      {me?.email.toLowerCase() !== inv.email.toLowerCase() ? (
        <Notice tone="amber">
          This invitation was sent to {inv.email}, but you are signed in as {me?.email}. Sign out and sign in with the invited address.
        </Notice>
      ) : (
        <Button
          className="w-full justify-center"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const r = await api<{ workspace_id: string }>("/api/v1/invitations/accept", { method: "POST", body: { token } });
              await refreshMe();
              switchWorkspace(r.workspace_id);
              toast.success(`You joined ${inv.workspace_name}`);
              navigate("/");
            } catch (e) {
              toast.error((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Accept invitation
        </Button>
      )}
    </AuthShell>
  );
}
