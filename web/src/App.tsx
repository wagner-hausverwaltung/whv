import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "@/auth/AuthContext";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { Layout } from "@/components/Layout";
import { ForgotPasswordPage } from "@/pages/ForgotPasswordPage";
import { InviteRedeemPage } from "@/pages/InviteRedeemPage";
import { LoginPage } from "@/pages/LoginPage";
import { PropertyDetailPage } from "@/pages/PropertyDetailPage";
import { PropertyDocumentsPage } from "@/pages/PropertyDocumentsPage";
import { PropertyListPage } from "@/pages/PropertyListPage";
import { ResetPasswordPage } from "@/pages/ResetPasswordPage";
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

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
