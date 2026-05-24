import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import {
  TICKET_CATEGORY_LABELS,
  TICKET_STATUS_LABELS,
  type TicketResponse,
} from "@/api/types";

function StatusBadge({ status }: { status: TicketResponse["status"] }) {
  const tone =
    status === "GESCHLOSSEN"
      ? "bg-slate-100 text-slate-600 border-slate-200"
      : status === "WARTET_AUF_KUNDE"
        ? "bg-amber-50 text-amber-900 border-amber-200"
        : "bg-blue-50 text-whv-blue border-blue-200";
  return (
    <span
      className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${tone}`}
    >
      {TICKET_STATUS_LABELS[status]}
    </span>
  );
}

export function TicketListPage() {
  const [tickets, setTickets] = useState<TicketResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<TicketResponse[]>("/me/tickets")
      .then((r) => setTickets(r.data))
      .catch(() => setError("Tickets konnten nicht geladen werden."));
  }, []);

  if (error) return <p className="flash-error">{error}</p>;
  if (tickets === null) return <p className="muted">Wird geladen…</p>;

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">Meine Tickets</h1>
        <Link to="/tickets/new" className="btn-primary">
          + Neues Ticket
        </Link>
      </header>

      {tickets.length === 0 ? (
        <p className="muted">
          Sie haben noch keine Tickets eröffnet. Verwenden Sie diesen Kanal für
          Anfragen, Schadensmeldungen oder Hinweise an die Hausverwaltung.
        </p>
      ) : (
        <ul className="space-y-2">
          {tickets.map((t) => (
            <li key={t.id}>
              <Link
                to={`/tickets/${t.id}`}
                className="card block hover:border-whv-blue transition-colors"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-display font-medium text-whv-text">
                      {t.subject}
                    </div>
                    <div className="muted mt-1">
                      {TICKET_CATEGORY_LABELS[t.category]} · letzte Aktivität{" "}
                      {new Date(t.last_message_at).toLocaleString("de-DE")}
                    </div>
                  </div>
                  <StatusBadge status={t.status} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
