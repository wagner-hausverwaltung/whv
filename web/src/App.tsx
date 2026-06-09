import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AdminLayout } from "@/admin/AdminLayout";
import { AdminAnnouncementDetailPage } from "@/admin/pages/AdminAnnouncementDetailPage";
import { AdminAnnouncementsAllPage } from "@/admin/pages/AdminAnnouncementsAllPage";
import { AdminAssembliesPage } from "@/admin/pages/AdminAssembliesPage";
import { AdminAssemblyDetailPage } from "@/admin/pages/AdminAssemblyDetailPage";
import { AdminAssistantLogPage } from "@/admin/pages/AdminAssistantLogPage";
import { AdminAuditPage } from "@/admin/pages/AdminAuditPage";
import { AdminContactsPage } from "@/admin/pages/AdminContactsPage";
import { AdminContractsPage } from "@/admin/pages/AdminContractsPage";
import { AdminDashboardPage } from "@/admin/pages/AdminDashboardPage";
import { AdminInviteNewPage } from "@/admin/pages/AdminInviteNewPage";
import { AdminInvitesPage } from "@/admin/pages/AdminInvitesPage";
import { AdminPropertiesPage } from "@/admin/pages/AdminPropertiesPage";
import { AdminPropertyDetailPage } from "@/admin/pages/AdminPropertyDetailPage";
import { AdminResolutionDetailPage } from "@/admin/pages/AdminResolutionDetailPage";
import { AdminResolutionNewPage } from "@/admin/pages/AdminResolutionNewPage";
import { AdminResolutionsPage } from "@/admin/pages/AdminResolutionsPage";
import { AdminSignaturesPage } from "@/admin/pages/AdminSignaturesPage";
import { AdminTicketDetailPage } from "@/admin/pages/AdminTicketDetailPage";
import { AdminTicketsPage } from "@/admin/pages/AdminTicketsPage";
import { AdminUnitsPage } from "@/admin/pages/AdminUnitsPage";
import { AdminRoute } from "@/auth/AdminRoute";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { Layout } from "@/components/Layout";
import { PropertyWorkspace } from "@/components/PropertyWorkspace";
import { RootRedirect } from "@/components/RootRedirect";
import { ForgotPasswordPage } from "@/pages/ForgotPasswordPage";
import { HomePage } from "@/pages/HomePage";
import { MyAnnouncementDetailPage } from "@/pages/MyAnnouncementDetailPage";
import { MyAnnouncementsPage } from "@/pages/MyAnnouncementsPage";
import { MyAssembliesPage } from "@/pages/MyAssembliesPage";
import { MyAssemblyDetailPage } from "@/pages/MyAssemblyDetailPage";
import { InviteRedeemPage } from "@/pages/InviteRedeemPage";
import { PublicVotePage } from "@/pages/PublicVotePage";
import { LoginPage } from "@/pages/LoginPage";
import { PropertyDetailPage } from "@/pages/PropertyDetailPage";
import { PropertyDocumentsPage } from "@/pages/PropertyDocumentsPage";
import { PropertyVendorsPage } from "@/pages/PropertyVendorsPage";
import { PropertyAccountPage } from "@/pages/PropertyAccountPage";
import { PropertyStartPage } from "@/pages/PropertyStartPage";
import { ResetPasswordPage } from "@/pages/ResetPasswordPage";
import { ResolutionDetailPage } from "@/pages/ResolutionDetailPage";
import { ResolutionListPage } from "@/pages/ResolutionListPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { TicketDetailPage } from "@/pages/TicketDetailPage";
import { TicketListPage } from "@/pages/TicketListPage";
import { TicketNewPage } from "@/pages/TicketNewPage";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Pre-auth */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/invite" element={<InviteRedeemPage />} />
          <Route path="/abstimmung/:token" element={<PublicVotePage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />

          {/* Root: fetches /me/properties + redirects to first */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Layout>
                  <RootRedirect />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/home"
            element={
              <ProtectedRoute>
                <Layout>
                  <HomePage />
                </Layout>
              </ProtectedRoute>
            }
          />

          {/*
           * Property workspace — tab container under /properties/:id.
           * The bare path redirects to /details so direct hits land
           * on the default tab. Old bookmarks like
           * /properties/:id/announcements still hit the right tab
           * because each tab segment is a real child route.
           */}
          <Route
            path="/properties/:id"
            element={
              <ProtectedRoute>
                <Layout>
                  <PropertyWorkspace />
                </Layout>
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="start" replace />} />
            <Route path="start" element={<PropertyStartPage />} />
            <Route path="details" element={<PropertyDetailPage />} />
            <Route path="account" element={<PropertyAccountPage />} />
            <Route path="announcements" element={<MyAnnouncementsPage />} />
            <Route path="assemblies" element={<MyAssembliesPage />} />
            <Route path="documents" element={<PropertyDocumentsPage />} />
            <Route path="vendors" element={<PropertyVendorsPage />} />
          </Route>

          {/* Property-detail child pages — outside the workspace,
              full-canvas with their own breadcrumbs. */}
          <Route
            path="/announcements/:id"
            element={
              <ProtectedRoute>
                <Layout>
                  <MyAnnouncementDetailPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/assemblies/:id"
            element={
              <ProtectedRoute>
                <Layout>
                  <MyAssemblyDetailPage />
                </Layout>
              </ProtectedRoute>
            }
          />

          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <Layout>
                  <SettingsPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/tickets"
            element={
              <ProtectedRoute>
                <Layout>
                  <TicketListPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/tickets/new"
            element={
              <ProtectedRoute>
                <Layout>
                  <TicketNewPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/tickets/:id"
            element={
              <ProtectedRoute>
                <Layout>
                  <TicketDetailPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/resolutions"
            element={
              <ProtectedRoute>
                <Layout>
                  <ResolutionListPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/resolutions/:id"
            element={
              <ProtectedRoute>
                <Layout>
                  <ResolutionDetailPage />
                </Layout>
              </ProtectedRoute>
            }
          />

          {/* Admin SPA — Verwalter-only, mounted under /admin/*. Served
              from the admin.* host via Caddy rewrite root → /admin. */}
          <Route
            path="/admin"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminDashboardPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/tickets"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminTicketsPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/tickets/:id"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminTicketDetailPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/resolutions"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminResolutionsPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/resolutions/new"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminResolutionNewPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/resolutions/:id"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminResolutionDetailPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/signatures"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminSignaturesPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/assemblies"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminAssembliesPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/assemblies/:id"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminAssemblyDetailPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/invites"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminInvitesPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/invites/new"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminInviteNewPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/audit"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminAuditPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/assistant-log"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminAssistantLogPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/announcements"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminAnnouncementsAllPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/announcements/:id"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminAnnouncementDetailPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/properties"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminPropertiesPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/properties/:id"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminPropertyDetailPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/units"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminUnitsPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/contracts"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminContractsPage />
                </AdminLayout>
              </AdminRoute>
            }
          />
          <Route
            path="/admin/contacts"
            element={
              <AdminRoute>
                <AdminLayout>
                  <AdminContactsPage />
                </AdminLayout>
              </AdminRoute>
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
