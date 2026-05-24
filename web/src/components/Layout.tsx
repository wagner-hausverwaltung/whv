import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
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

      <footer className="border-t border-whv-border bg-white">
        <div className="max-w-5xl mx-auto px-6 py-4 muted text-xs flex items-center justify-between flex-wrap gap-2">
          <span>© Wagner Hausverwaltung GmbH</span>
          <a
            href="https://wagner-hausverwaltung.com/"
            target="_blank"
            rel="noreferrer"
            className="hover:underline"
          >
            wagner-hausverwaltung.com
          </a>
        </div>
      </footer>
    </div>
  );
}
