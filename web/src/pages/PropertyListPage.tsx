import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import type { PropertyResponse } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";

export function PropertyListPage() {
  const { user } = useAuth();
  const [properties, setProperties] = useState<PropertyResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PropertyResponse[]>("/me/properties")
      .then((r) => setProperties(r.data))
      .catch(() => setError("Objekte konnten nicht geladen werden."));
  }, []);

  if (error) return <p className="flash-error">{error}</p>;
  if (properties === null) return <p className="muted">Wird geladen…</p>;

  const isVerwalter = user?.role === "verwalter";
  const isUnbound =
    user && !isVerwalter && user.contact_id_impower === null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Meine Objekte</h1>
        {isVerwalter && (
          <p className="muted mt-2">
            Sie sind als Verwalter angemeldet und sehen alle Objekte der
            Organisation.{" "}
            <a
              href="https://admin.wagner-hausverwaltung.com/"
              className="hover:underline"
            >
              Verwaltungsfunktionen →
            </a>
          </p>
        )}
      </div>

      {properties.length === 0 ? (
        <p className="muted">
          {isUnbound
            ? "Ihr Konto ist noch nicht mit einem Impower-Kontakt verknüpft. Bitte wenden Sie sich an die Hausverwaltung."
            : "Keine Objekte gefunden."}
        </p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {properties.map((p) => (
            <li key={p.id}>
              <Link
                to={`/properties/${p.id}`}
                className="card block hover:border-whv-blue transition-colors group"
              >
                <div className="font-display font-medium text-whv-text group-hover:text-whv-blue">
                  {p.name}
                </div>
                <div className="muted mt-2">
                  {[
                    p.street && [p.street, p.number].filter(Boolean).join(" "),
                    [p.postal_code, p.city].filter(Boolean).join(" "),
                  ]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </div>
                {p.property_hr_id && (
                  <div className="muted mt-1 font-mono text-xs">
                    {p.property_hr_id}
                  </div>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
