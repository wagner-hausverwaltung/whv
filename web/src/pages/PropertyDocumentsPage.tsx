import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import type { DocumentResponse } from "@/api/types";

function formatBytes(bytes: number | null): string {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function PropertyDocumentsPage() {
  const { id } = useParams<{ id: string }>();
  const [docs, setDocs] = useState<DocumentResponse[] | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!id) return;
    api
      .get<DocumentResponse[]>(`/me/properties/${id}/documents`)
      .then((r) => setDocs(r.data))
      .catch((err) => {
        if (err.response?.status === 404) setNotFound(true);
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
  if (docs === null) return <p className="muted">Wird geladen…</p>;

  return (
    <div className="space-y-8">
      <Link to={`/properties/${id}`} className="muted hover:underline inline-block">
        ← Objektdetails
      </Link>

      <header className="space-y-2">
        <h1 className="text-2xl font-bold">Dokumente</h1>
        <p className="muted">
          Datei-Downloads kommen mit dem nächsten Update — derzeit sehen Sie nur
          die Metadaten der vom Hausverwalter hinterlegten Dokumente.
        </p>
      </header>

      {docs.length === 0 ? (
        <p className="muted">Keine Dokumente erfasst.</p>
      ) : (
        <div className="overflow-x-auto card !p-0">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Art</th>
                <th>Datum</th>
                <th>Größe</th>
                <th>Typ</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td className="text-xs uppercase tracking-wide muted">
                    {d.kind}
                  </td>
                  <td>{d.issued_date ?? "—"}</td>
                  <td>{formatBytes(d.size_bytes)}</td>
                  <td className="muted text-xs">{d.mime_type ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
