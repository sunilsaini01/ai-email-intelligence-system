import { BrowserRouter, Route, Routes } from "react-router-dom";
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
import { ReportsPage } from "./pages/ReportsPage";
import { useDashboardWebSocket } from "./hooks/useDashboardWebSocket";

function AppRoutes() {
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
        <Route path="reports" element={<ReportsPage />} />
      </Route>
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
