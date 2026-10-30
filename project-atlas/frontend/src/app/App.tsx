import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../services/api";
import { useAtlas } from "./store";
import { Layout } from "./Layout";
import { Spinner } from "../components/ui";
import { Login } from "../features/auth/Login";
import { Home } from "../features/home/Home";
import { Catalog, DatasetDetail } from "../features/catalog/Catalog";
import { Ingestion } from "../features/ingestion/Ingestion";
import { SearchPage } from "../features/search/Search";
import { EntityExplorer, EntityDetail } from "../features/entities/Entities";
import { GraphPage } from "../features/graph/Graph";
import { TimelinePage } from "../features/timeline/Timeline";
import { GeoPage } from "../features/maps/Geo";
import { AnalyticsPage } from "../features/analytics/Analytics";
import { DocumentsPage } from "../features/documents/Documents";
import { InvestigationsPage, InvestigationDetail } from "../features/investigations/Investigations";
import { WorkflowsPage } from "../features/workflows/Workflows";
import { ReportsPage } from "../features/reports/Reports";
import { AuditPage } from "../features/audit/Audit";
import { AdminPage } from "../features/admin/Admin";
import { SettingsPage } from "../features/settings/Settings";
import { ProjectsPage } from "../features/home/Projects";

export function App() {
  const { token, user, setUser, setSession } = useAtlas();
  const me = useQuery({ queryKey: ["me", token], queryFn: () => api("/api/auth/me"), enabled: !!token });
  useEffect(() => {
    if (me.data) setUser(me.data);
    if (me.error) setSession(null, null);
  }, [me.data, me.error, setUser, setSession]);

  if (!token) return <Login />;
  if (!user) return <div className="flex h-full items-center justify-center"><Spinner label="Opening Project Atlas…" /></div>;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="catalog" element={<Catalog />} />
        <Route path="catalog/:datasetId" element={<DatasetDetail />} />
        <Route path="ingestion" element={<Ingestion />} />
        <Route path="search" element={<SearchPage />} />
        <Route path="entities" element={<EntityExplorer />} />
        <Route path="entities/:entityId" element={<EntityDetail />} />
        <Route path="graph" element={<GraphPage />} />
        <Route path="timeline" element={<TimelinePage />} />
        <Route path="geo" element={<GeoPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="investigations" element={<InvestigationsPage />} />
        <Route path="investigations/:invId" element={<InvestigationDetail />} />
        <Route path="workflows" element={<WorkflowsPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
