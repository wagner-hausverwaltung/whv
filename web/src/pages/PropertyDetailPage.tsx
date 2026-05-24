import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import type { PropertyDetailResponse } from "@/api/types";

export function PropertyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [prop, setProp] = useState<PropertyDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!id) return;
    api
      .get<PropertyDetailResponse>(`/me/properties/${id}`)
      .then((r) => setProp(r.data))
      .catch((err) => {
        if (err.response?.status === 404) setNotFound(true);
        else setError("Objektdetails konnten nicht geladen werden.");
      });
  }, [id]);

  if (notFound) {
    return (
      <div className="space-y-4">
        <p className="flash-error">Objekt nicht gefunden oder nicht zugänglich.</p>
        <Link to="/" className="muted hover:underline">
          ← Zurück zur Übersicht
        </Link>
      </div>
    );
  }
  if (error) return <p className="flash-error">{error}</p>;
  if (!prop) return <p className="muted">Wird geladen…</p>;

  const address = [
    [prop.street, prop.number].filter(Boolean).join(" "),
    [prop.postal_code, prop.city].filter(Boolean).join(" "),
    prop.country,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="space-y-8">
      <Link to="/" className="muted hover:underline inline-block">
        ← Meine Objekte
      </Link>

      <header className="space-y-1">
        <h1 className="text-2xl font-bold">{prop.name}</h1>
        {prop.property_hr_id && (
          <p className="muted font-mono text-xs">{prop.property_hr_id}</p>
        )}
      </header>

      <section className="card space-y-2">
        <h2 className="font-semibold text-sm uppercase tracking-wide text-whv-muted mb-3">
          Stammdaten
        </h2>
        {address && (
          <p>
            <span className="muted">Adresse: </span>
            <span className="text-whv-text">{address}</span>
          </p>
        )}
        <p>
          <span className="muted">Typ: </span>
          <span className="text-whv-text">{prop.type}</span>
        </p>
        <p>
          <span className="muted">Status: </span>
          <span className="text-whv-text">{prop.state}</span>
        </p>
      </section>

      <section>
        <h2 className="font-semibold text-sm uppercase tracking-wide text-whv-muted mb-3">
          Einheiten ({prop.units.length})
        </h2>
        {prop.units.length === 0 ? (
          <p className="muted">Keine Einheiten erfasst.</p>
        ) : (
          <div className="overflow-x-auto card !p-0">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Bezeichnung</th>
                  <th>Typ</th>
                  <th>Etage</th>
                  <th>Lage</th>
                  <th>m²</th>
                  <th>Zimmer</th>
                </tr>
              </thead>
              <tbody>
                {prop.units.map((u) => (
                  <tr key={u.id}>
                    <td className="font-mono text-xs">
                      {u.unit_hr_id ?? "—"}
                    </td>
                    <td>{u.type}</td>
                    <td>{u.floor ?? "—"}</td>
                    <td>{u.position ?? "—"}</td>
                    <td>{u.area_m2 ?? "—"}</td>
                    <td>{u.rooms ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <Link
          to={`/properties/${prop.id}/documents`}
          className="btn-secondary inline-block"
        >
          Dokumente ansehen →
        </Link>
      </section>
    </div>
  );
}
