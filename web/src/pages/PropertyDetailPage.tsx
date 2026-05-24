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
    <div className="space-y-6">
      <div>
        <Link to="/" className="muted hover:underline">
          ← Meine Objekte
        </Link>
      </div>

      <div>
        <h1 className="text-2xl font-bold text-slate-900">{prop.name}</h1>
        {prop.property_hr_id && (
          <p className="muted font-mono text-xs mt-1">{prop.property_hr_id}</p>
        )}
      </div>

      <section className="card space-y-2">
        <h2 className="font-semibold">Stammdaten</h2>
        {address && (
          <p>
            <span className="muted">Adresse: </span>
            {address}
          </p>
        )}
        <p>
          <span className="muted">Typ: </span>
          {prop.type}
        </p>
        <p>
          <span className="muted">Status: </span>
          {prop.state}
        </p>
      </section>

      <section>
        <h2 className="font-semibold mb-3">
          Einheiten ({prop.units.length})
        </h2>
        {prop.units.length === 0 ? (
          <p className="muted">Keine Einheiten erfasst.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-slate-500 border-b border-slate-200">
                <tr>
                  <th className="py-2 pr-4">Bezeichnung</th>
                  <th className="py-2 pr-4">Typ</th>
                  <th className="py-2 pr-4">Etage</th>
                  <th className="py-2 pr-4">Lage</th>
                  <th className="py-2 pr-4">m²</th>
                  <th className="py-2">Zimmer</th>
                </tr>
              </thead>
              <tbody>
                {prop.units.map((u) => (
                  <tr key={u.id} className="border-b border-slate-100">
                    <td className="py-2 pr-4 font-mono text-xs">
                      {u.unit_hr_id ?? "—"}
                    </td>
                    <td className="py-2 pr-4">{u.type}</td>
                    <td className="py-2 pr-4">{u.floor ?? "—"}</td>
                    <td className="py-2 pr-4">{u.position ?? "—"}</td>
                    <td className="py-2 pr-4">{u.area_m2 ?? "—"}</td>
                    <td className="py-2">{u.rooms ?? "—"}</td>
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
