import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Box, CircularProgress } from "@mui/material";
import { useAuth } from "./AuthContext";

// Stricter than ProtectedRoute — requires the caller to be a Verwalter.
// Non-Verwalter authenticated users are redirected to the portal root so
// they don't see a confusing "denied" page when they wander into /admin/*.
export function AdminRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <Box
        sx={{
          minHeight: "60vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <CircularProgress size={28} />
      </Box>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (user.role !== "verwalter") {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
