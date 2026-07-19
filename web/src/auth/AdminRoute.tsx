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

  // Domain <-> surface separation, the mirror of the owner redirect below:
  // both hosts serve the same bundle, so portal.*/admin/* would happily
  // render the admin UI (Safari's compact URL bar hides the /admin path --
  // it looks like "the portal shows the admin"). Bounce to the admin host,
  // keeping the path. Local dev has no "portal." prefix and is unaffected.
  const host = window.location.hostname;
  if (host.includes("portal.")) {
    window.location.replace(
      `https://${host.replace("portal.", "admin.")}${location.pathname}${location.search}`,
    );
    return null;
  }

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
    // On the admin host, "/" would still render the portal UI under the
    // wrong domain (feedback: owners could log in on admin.* and got a
    // confusing portal there). Send them to the real portal host instead.
    if (host.includes("admin.")) {
      window.location.replace(`https://${host.replace("admin.", "portal.")}/`);
      return null;
    }
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
