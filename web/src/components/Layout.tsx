import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Footer } from "@/components/Footer";
import type { ReactNode } from "react";

export function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const onLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-whv-border bg-white">
        <div className="max-w-5xl mx-auto px-6 py-3 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-3" aria-label="Wagner Hausverwaltung — Portal">
            <img
              src="/wagner-logo.png"
              alt="Wagner Hausverwaltung GmbH"
              className="h-10 w-auto"
            />
            <span className="muted hidden sm:inline">Portal</span>
          </Link>
          {user && (
            <div className="flex items-center gap-4">
              <Link to="/" className="muted hover:text-whv-blue hidden sm:inline">
                Objekte
              </Link>
              <Link to="/tickets" className="muted hover:text-whv-blue">
                Tickets
              </Link>
              <Link to="/resolutions" className="muted hover:text-whv-blue">
                Beschlüsse
              </Link>
              <Link
                to="/settings"
                className="muted hover:text-whv-blue hidden sm:inline"
              >
                {user.email}
              </Link>
              <button
                type="button"
                className="btn-secondary text-xs px-3 py-1.5"
                onClick={onLogout}
              >
                Abmelden
              </button>
            </div>
          )}
        </div>
      </header>

      <main className="flex-1 max-w-5xl w-full mx-auto px-6 py-10">{children}</main>

      <Footer />
    </div>
  );
}
