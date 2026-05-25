import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AdminLayout } from "@/admin/AdminLayout";
import { AdminAnnouncementDetailPage } from "@/admin/pages/AdminAnnouncementDetailPage";
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
import { AdminTicketDetailPage } from "@/admin/pages/AdminTicketDetailPage";
import { AdminTicketsPage } from "@/admin/pages/AdminTicketsPage";
import { AdminUnitsPage } from "@/admin/pages/AdminUnitsPage";
import { AdminRoute } from "@/auth/AdminRoute";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { Layout } from "@/components/Layout";
import { ForgotPasswordPage } from "@/pages/ForgotPasswordPage";
import { MyAnnouncementDetailPage } from "@/pages/MyAnnouncementDetailPage";
import { MyAnnouncementsPage } from "@/pages/MyAnnouncementsPage";
import { InviteRedeemPage } from "@/pages/InviteRedeemPage";
import { LoginPage } from "@/pages/LoginPage";
import { PropertyDetailPage } from "@/pages/PropertyDetailPage";
import { PropertyDocumentsPage } from "@/pages/PropertyDocumentsPage";
import { PropertyListPage } from "@/pages/PropertyListPage";
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
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />

          {/* Authenticated */}
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Layout>
                  <PropertyListPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/properties/:id"
            element={
              <ProtectedRoute>
                <Layout>
                  <PropertyDetailPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/properties/:id/documents"
            element={
              <ProtectedRoute>
                <Layout>
                  <PropertyDocumentsPage />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/properties/:id/announcements"
            element={
              <ProtectedRoute>
                <Layout>
                  <MyAnnouncementsPage />
                </Layout>
              </ProtectedRoute>
            }
          />
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
