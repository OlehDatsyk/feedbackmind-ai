import { lazy, Suspense, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppLayout } from "./components/layout";
import { Button, EmptyState, LoadingBlock } from "./components/ui";
import { useAuth } from "./lib/auth";
import { AcceptInvitePage, LoginPage, RegisterPage } from "./pages/AuthPages";
import { OverviewPage } from "./pages/OverviewPage";

const FeedbackPage = lazy(() => import("./pages/FeedbackPage"));
const FeedbackDetailPage = lazy(() => import("./pages/FeedbackDetailPage"));
const ImportsPage = lazy(() => import("./pages/ImportsPage"));
const TopicsPage = lazy(() => import("./pages/TopicsPage"));
const InsightsPage = lazy(() => import("./pages/InsightsPage"));
const TrendsPage = lazy(() => import("./pages/TrendsPage"));
const AnalystPage = lazy(() => import("./pages/AnalystPage"));
const AlertsPage = lazy(() => import("./pages/AlertsPage"));
const ComparisonsPage = lazy(() => import("./pages/ComparisonsPage"));
const ReportsPage = lazy(() => import("./pages/ReportsPage"));
const IntegrationsPage = lazy(() => import("./pages/IntegrationsPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));

function Protected({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading, me } = useAuth();
  const location = useLocation();
  if (isLoading) {
    return (
      <div className="mx-auto max-w-3xl p-10">
        <LoadingBlock rows={6} />
      </div>
    );
  }
  if (!isAuthenticated) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (me && me.workspaces.length === 0 && location.pathname !== "/settings") return <Navigate to="/settings?tab=workspaces" replace />;
  return <>{children}</>;
}

function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      description="The page you are looking for does not exist or you do not have access to it."
      action={
        <Link to="/">
          <Button>Back to overview</Button>
        </Link>
      }
    />
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/invite/:token" element={<AcceptInvitePage />} />
      <Route
        element={
          <Protected>
            <AppLayout />
          </Protected>
        }
      >
        <Route index element={<OverviewPage />} />
        {[
          ["feedback", <FeedbackPage />],
          ["feedback/:id", <FeedbackDetailPage />],
          ["imports", <ImportsPage />],
          ["topics", <TopicsPage />],
          ["insights", <InsightsPage />],
          ["trends", <TrendsPage />],
          ["analyst", <AnalystPage />],
          ["alerts", <AlertsPage />],
          ["comparisons", <ComparisonsPage />],
          ["reports", <ReportsPage />],
          ["integrations", <IntegrationsPage />],
          ["settings", <SettingsPage />],
        ].map(([path, el]) => (
          <Route key={path as string} path={path as string} element={<Suspense fallback={<LoadingBlock rows={6} />}>{el}</Suspense>} />
        ))}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
