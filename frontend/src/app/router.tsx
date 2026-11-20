import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Spinner } from "../components/ui/spinner";
import { ProtectedRoute } from "../features/auth/components/protected-route";
import { GuestRoute } from "../features/auth/components/guest-route";
import { AppLayout } from "../components/layout/app-layout";

const LoginPage = lazy(() => import("../features/auth/pages/login-page").then((module) => ({ default: module.LoginPage })));
const RegisterPage = lazy(() => import("../features/auth/pages/register-page").then((module) => ({ default: module.RegisterPage })));
const DashboardPage = lazy(() => import("../features/dashboard/pages/dashboard-page").then((module) => ({ default: module.DashboardPage })));
const AgentsPage = lazy(() => import("../features/agents/pages/agents-page").then((module) => ({ default: module.AgentsPage })));
const ConnectionsPage = lazy(() => import("../features/connections/pages/connections-page").then((module) => ({ default: module.ConnectionsPage })));
const DocumentsPage = lazy(() => import("../features/documents/pages/documents-page").then((module) => ({ default: module.DocumentsPage })));
const GroupDetailsPage = lazy(() => import("../features/groups/pages/group-details-page").then((module) => ({ default: module.GroupDetailsPage })));
const GroupsPage = lazy(() => import("../features/groups/pages/groups-page").then((module) => ({ default: module.GroupsPage })));
const NotificationsPage = lazy(() => import("../features/notifications/pages/notifications-page").then((module) => ({ default: module.NotificationsPage })));
const SettingsPage = lazy(() => import("../features/settings/pages/settings-page").then((module) => ({ default: module.SettingsPage })));

export function AppRouter() {
  return (
    <Suspense fallback={<div className="flex min-h-screen items-center justify-center bg-[#f8f9fc]"><Spinner className="h-6 w-6 text-brand-600" /></div>}>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route element={<GuestRoute />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/groups" element={<GroupsPage />} />
            <Route path="/groups/:groupId" element={<GroupDetailsPage />} />
            <Route path="/groups/:groupId/chat" element={<GroupDetailsPage />} />
            <Route path="/connections" element={<ConnectionsPage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/documents" element={<DocumentsPage />} />
            <Route path="/notifications" element={<NotificationsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Suspense>
  );
}
