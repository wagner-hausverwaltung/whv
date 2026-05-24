import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import {
  RESOLUTION_MODE_LABELS,
  RESOLUTION_STATUS_LABELS,
  type ResolutionResponse,
} from "@/api/types";

function StatusBadge({ status }: { status: ResolutionResponse["status"] }) {
  const tone =
    status === "ANGENOMMEN"
      ? "bg-emerald-50 text-emerald-900 border-emerald-200"
      : status === "ABGELEHNT"
        ? "bg-red-50 text-red-900 border-red-200"
        : status === "OFFEN"
          ? "bg-blue-50 text-whv-blue border-blue-200"
          : "bg-slate-100 text-slate-600 border-slate-200";
  return (
    <span
      className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${tone}`}
    >
      {RESOLUTION_STATUS_LABELS[status]}
    </span>
  );
}

export function ResolutionListPage() {
  const [rows, setRows] = useState<ResolutionResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ResolutionResponse[]>("/me/resolutions")
      .then((r) => setRows(r.data))
      .catch(() => setError("Beschlüsse konnten nicht geladen werden."));
  }, []);

  if (error) return <p className="flash-error">{error}</p>;
  if (rows === null) return <p className="muted">Wird geladen…</p>;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Umlaufbeschlüsse</h1>
        <p className="muted mt-1">
          Hier sehen Sie alle Umlaufbeschlüsse zu Ihren Liegenschaften und
          können während der Frist Ihre Stimme abgeben.
        </p>
      </header>

      {rows.length === 0 ? (
        <p className="muted">Keine Beschlüsse vorhanden.</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.id}>
              <Link
                to={`/resolutions/${r.id}`}
                className="card block hover:border-whv-blue transition-colors"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-display font-medium text-whv-text">
                      {r.title}
                    </div>
                    <div className="muted mt-1">
                      {RESOLUTION_MODE_LABELS[r.mode]} · Frist{" "}
                      {new Date(r.closes_at).toLocaleString("de-DE")}
                    </div>
                  </div>
                  <StatusBadge status={r.status} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
