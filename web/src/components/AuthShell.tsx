import type { ReactNode } from "react";
import { Footer } from "@/components/Footer";

// Shared chrome for pre-auth pages (login, invite redeem, forgot/reset).
// Library background (Stadtbibliothek Stuttgart) sits behind a near-opaque
// white overlay so the form card remains readable, with just enough of the
// image bleeding through to give the page a sense of place.
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
    <div className="min-h-screen flex flex-col bg-whv-bg relative">
      {/* Background image — fixed so it doesn't scroll with the form. */}
      <div
        aria-hidden="true"
        className="fixed inset-0 -z-10 bg-cover bg-center"
        style={{ backgroundImage: "url('/library.webp')" }}
      />
      {/* Semi-transparent overlay tones the image down (form stays readable). */}
      <div
        aria-hidden="true"
        className="fixed inset-0 -z-10 bg-white/70 backdrop-blur-[2px]"
      />

      <main className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm space-y-6">
          <div className="flex justify-center">
            <img
              src="/wagner-logo.png"
              alt="Wagner Hausverwaltung GmbH"
              className="h-20 w-auto"
            />
          </div>
          <div className="card space-y-5 shadow-sm">
            <div className="space-y-1.5">
              <h1 className="text-xl font-bold">{title}</h1>
              {subtitle && <p className="muted">{subtitle}</p>}
            </div>
            {children}
          </div>
        </div>
      </main>

      <Footer />
    </div>
  );
}
