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

  if (error) {
    return <p className="flash-error">{error}</p>;
  }
  if (properties === null) {
    return <p className="muted">Wird geladen…</p>;
  }

  const isUnbound =
    user && user.role !== "verwalter" && user.contact_id_impower === null;

  if (properties.length === 0) {
    return (
      <div className="space-y-3">
        <h1 className="text-xl font-bold">Meine Objekte</h1>
        <p className="muted">
          {isUnbound
            ? "Ihr Konto ist noch nicht mit einem Impower-Kontakt verknüpft. Bitte wenden Sie sich an die Hausverwaltung."
            : "Keine Objekte gefunden."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Meine Objekte</h1>
      <ul className="space-y-3">
        {properties.map((p) => (
          <li key={p.id}>
            <Link
              to={`/properties/${p.id}`}
              className="card block hover:border-slate-400 hover:shadow transition"
            >
              <div className="font-medium text-slate-900">{p.name}</div>
              <div className="muted mt-1">
                {[p.street && [p.street, p.number].filter(Boolean).join(" "), p.city]
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
    </div>
  );
}
