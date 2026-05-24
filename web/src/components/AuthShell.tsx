import type { ReactNode } from "react";
import { Link } from "react-router-dom";

// Shared chrome for pre-auth pages (login, invite redeem, forgot/reset).
// Branded header strip + centered card on a soft background.
export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen flex flex-col bg-whv-bg">
      <header className="border-b border-whv-border bg-white">
        <div className="max-w-5xl mx-auto px-6 py-4">
          <Link
            to="/login"
            className="font-display font-bold text-whv-text hover:text-whv-blue text-base tracking-tight"
          >
            Wagner Hausverwaltung
            <span className="muted ml-2 font-sans font-normal">Portal</span>
          </Link>
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="card space-y-5">
            <div className="space-y-1.5">
              <h1 className="text-xl font-bold">{title}</h1>
              {subtitle && <p className="muted">{subtitle}</p>}
            </div>
            {children}
          </div>
        </div>
      </main>

      <footer className="border-t border-whv-border bg-white">
        <div className="max-w-5xl mx-auto px-6 py-4 muted text-xs">
          © Wagner Hausverwaltung GmbH
        </div>
      </footer>
    </div>
  );
}
