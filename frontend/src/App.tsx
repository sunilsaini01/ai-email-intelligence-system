import type { ReactElement } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { OverviewPage } from "./pages/OverviewPage";
import { EmailVolumePage } from "./pages/EmailVolumePage";
import { CategoriesPage } from "./pages/CategoriesPage";
import { SentimentPage } from "./pages/SentimentPage";
import { PriorityPage } from "./pages/PriorityPage";
import { SlaPage } from "./pages/SlaPage";
import { AgentsPage } from "./pages/AgentsPage";
import { ModelQualityPage } from "./pages/ModelQualityPage";
import { ReviewQueuePage } from "./pages/ReviewQueuePage";
import { ReplyDraftsPage } from "./pages/ReplyDraftsPage";
import { RoutingRulesPage } from "./pages/RoutingRulesPage";
import { ReportsPage } from "./pages/ReportsPage";
import { LoginPage } from "./pages/LoginPage";
import { AdminPage } from "./pages/AdminPage";
import { AcceptInvitationPage, CreateOrganizationPage } from "./pages/SignupPages";
import { useDashboardWebSocket } from "./hooks/useDashboardWebSocket";
import { useAuth } from "./hooks/useAuth";

// Gates every dashboard route behind a valid session -- the backend
// already rejects these calls with 401 without a token (Phase 17), this
// just avoids firing them and then bouncing the user after the fact.
function RequireAuth({ children }: { children: ReactElement }) {
  const { user, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <div className="state-message">Loading…</div>;
  }
  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return children;
}

function DashboardRoutes() {
  useDashboardWebSocket();

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<OverviewPage />} />
        <Route path="email-volume" element={<EmailVolumePage />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="sentiment" element={<SentimentPage />} />
        <Route path="priority" element={<PriorityPage />} />
        <Route path="sla" element={<SlaPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="models" element={<ModelQualityPage />} />
        <Route path="review-queue" element={<ReviewQueuePage />} />
        <Route path="reply-drafts" element={<ReplyDraftsPage />} />
        <Route path="routing-rules" element={<RoutingRulesPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="admin" element={<AdminPage />} />
      </Route>
    </Routes>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<CreateOrganizationPage />} />
      <Route path="/accept-invitation" element={<AcceptInvitationPage />} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <DashboardRoutes />
          </RequireAuth>
        }
      />
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}

export default App;
