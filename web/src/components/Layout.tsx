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
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link to="/" className="font-bold text-slate-900">
            WHV-Portal
          </Link>
          {user && (
            <div className="flex items-center gap-3">
              <Link
                to="/settings"
                className="muted hover:underline hidden sm:inline"
              >
                {user.email}
              </Link>
              <button
                type="button"
                className="btn-secondary text-xs"
                onClick={onLogout}
              >
                Abmelden
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="max-w-4xl mx-auto px-4 py-6">{children}</main>
    </div>
  );
}
