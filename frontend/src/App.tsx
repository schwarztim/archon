import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, RequireAuth, useAuth } from "@/providers/auth-provider";
import { ThemeProvider } from "@/providers/theme-provider";
import { AppLayout } from "@/layouts/AppLayout";
import { DashboardPage } from "@/pages/DashboardPage";
import { AgentsPage } from "@/pages/AgentsPage";
import { BuilderPage } from "@/pages/BuilderPage";
import { TemplatesPage } from "@/pages/TemplatesPage";
import { ExecutionsPage } from "@/pages/ExecutionsPage";
import { ExecutionDetailPage } from "@/pages/ExecutionDetailPage";
import { WorkflowsPage } from "@/pages/WorkflowsPage";
import { ModelRouterPage } from "@/pages/ModelRouterPage";
import { LifecyclePage } from "@/pages/LifecyclePage";
import { CostPage } from "@/pages/CostPage";
import { DLPPage } from "@/pages/DLPPage";
import { RedTeamPage } from "@/pages/RedTeamPage";
import { SentinelScanPage } from "@/pages/SentinelScanPage";
import { GuardrailsPage } from "@/pages/GuardrailsPage";
import { GovernancePage } from "@/pages/GovernancePage";
import { AuditPage } from "@/pages/AuditPage";
import { ConnectorsPage } from "@/pages/ConnectorsPage";
import { DocForgePage } from "@/pages/DocForgePage";
import { MCPAppsPage } from "@/pages/MCPAppsPage";
import { MarketplacePage } from "@/pages/MarketplacePage";
import { TenantsPage } from "@/pages/TenantsPage";
import { SSOConfigPage } from "@/pages/SSOConfigPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { LoginPage } from "@/pages/LoginPage";
import { MFAChallengePage } from "@/pages/MFAChallengePage";
import { AuditLogPage } from "@/pages/admin/AuditLogPage";
import { SecretsPage } from "@/pages/admin/SecretsPage";
import { UsersPage } from "@/pages/admin/UsersPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
});

function AuthGate() {
  const { user, loading, mfaChallenge } = useAuth();

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <p className="text-gray-400">Loading…</p>
      </div>
    );
  }

  if (mfaChallenge) return <MFAChallengePage />;
  if (!user) return <LoginPage />;

  return (
    <RequireAuth>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<DashboardPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="agents/:id/edit" element={<AgentsPage />} />
          <Route path="builder" element={<BuilderPage />} />
          <Route path="templates" element={<TemplatesPage />} />
          <Route path="executions" element={<ExecutionsPage />} />
          <Route path="executions/:id" element={<ExecutionDetailPage />} />
          <Route path="workflows" element={<WorkflowsPage />} />
          <Route path="router" element={<ModelRouterPage />} />
          <Route path="lifecycle" element={<LifecyclePage />} />
          <Route path="cost" element={<CostPage />} />
          <Route path="dlp" element={<DLPPage />} />
          <Route path="redteam" element={<RedTeamPage />} />
          <Route path="sentinelscan" element={<SentinelScanPage />} />
          <Route path="guardrails" element={<GuardrailsPage />} />
          <Route path="governance" element={<GovernancePage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="connectors" element={<ConnectorsPage />} />
          <Route path="mcp-apps" element={<MCPAppsPage />} />
          <Route path="docforge" element={<DocForgePage />} />
          <Route path="marketplace" element={<MarketplacePage />} />
          <Route path="tenants" element={<TenantsPage />} />
          <Route path="tenants/:tenantId" element={<TenantsPage />} />
          <Route path="sso" element={<SSOConfigPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="admin/users" element={<UsersPage />} />
          <Route path="admin/secrets" element={<SecretsPage />} />
          <Route path="admin/audit" element={<AuditLogPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </RequireAuth>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <Routes>
              <Route path="/*" element={<AuthGate />} />
            </Routes>
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
