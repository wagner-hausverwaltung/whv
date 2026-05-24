import type { ReactNode } from "react";

// Shared chrome for pre-auth pages (login, invite redeem, forgot/reset).
// Logo-as-splash above the card — no header strip; the login is the brand
// surface itself rather than a chrome-wrapped form.
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
      <main className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm space-y-6">
          <div className="flex justify-center">
            <img
              src="/wagner-logo.png"
              alt="Wagner Hausverwaltung GmbH"
              className="h-20 w-auto"
            />
          </div>
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
