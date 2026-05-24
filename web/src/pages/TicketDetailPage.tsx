import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import {
  TICKET_CATEGORY_LABELS,
  TICKET_STATUS_LABELS,
  type TicketDetailResponse,
} from "@/api/types";

export function TicketDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const [ticket, setTicket] = useState<TicketDetailResponse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [posting, setPosting] = useState(false);
  const [closing, setClosing] = useState(false);

  const refresh = async () => {
    if (!id) return;
    try {
      const r = await api.get<TicketDetailResponse>(`/me/tickets/${id}`);
      setTicket(r.data);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 404) setNotFound(true);
      else setError("Ticket konnte nicht geladen werden.");
    }
  };

  useEffect(() => {
    // Initial fetch on mount + when ticket id changes. refresh() setState's
    // ticket/error — canonical "fetch on mount" pattern.
    // eslint-disable-next-line react-hooks/exhaustive-deps, react-hooks/set-state-in-effect
    void refresh();
  }, [id]);

  if (notFound) {
    return (
      <div className="space-y-4">
        <p className="flash-error">Ticket nicht gefunden oder nicht zugänglich.</p>
        <Link to="/tickets" className="muted hover:underline">
          ← Zurück zu meinen Tickets
        </Link>
      </div>
    );
  }
  if (error) return <p className="flash-error">{error}</p>;
  if (!ticket) return <p className="muted">Wird geladen…</p>;

  const isClosed = ticket.status === "GESCHLOSSEN";
  const canClose = !isClosed && user?.id === ticket.created_by_user_id;

  const onReply = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setPosting(true);
    try {
      await api.post(`/me/tickets/${ticket.id}/messages`, {
        body: reply.trim(),
        is_internal_note: false,
      });
      setReply("");
      await refresh();
    } catch {
      setError("Antwort konnte nicht gesendet werden.");
    } finally {
      setPosting(false);
    }
  };

  const onClose = async () => {
    if (!confirm("Ticket wirklich schließen?")) return;
    setClosing(true);
    try {
      await api.post(`/me/tickets/${ticket.id}/close`);
      await refresh();
    } catch {
      setError("Ticket konnte nicht geschlossen werden.");
    } finally {
      setClosing(false);
    }
  };

  return (
    <div className="space-y-6">
      <Link to="/tickets" className="muted hover:underline inline-block">
        ← Meine Tickets
      </Link>

      <header className="space-y-1">
        <h1 className="text-2xl font-bold">{ticket.subject}</h1>
        <p className="muted">
          {TICKET_CATEGORY_LABELS[ticket.category]} ·{" "}
          {TICKET_STATUS_LABELS[ticket.status]} · erstellt{" "}
          {new Date(ticket.created_at).toLocaleString("de-DE")}
          {ticket.closed_at && (
            <>
              {" "}
              · geschlossen {new Date(ticket.closed_at).toLocaleString("de-DE")}
            </>
          )}
        </p>
      </header>

      {error && <p className="flash-error">{error}</p>}

      <section className="space-y-3">
        {ticket.messages.map((m) => {
          const isMine = m.author_user_id === user?.id;
          return (
            <article
              key={m.id}
              className={`card ${isMine ? "border-whv-blue" : ""}`}
            >
              <header className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium">
                  {isMine ? "Sie" : "Wagner Hausverwaltung"}
                </span>
                <span className="muted text-xs">
                  {new Date(m.created_at).toLocaleString("de-DE")}
                </span>
              </header>
              <p className="whitespace-pre-wrap text-sm leading-6">{m.body}</p>
            </article>
          );
        })}
      </section>

      {isClosed ? (
        <p className="muted">
          Dieses Ticket ist geschlossen. Für eine neue Frage erstellen Sie bitte
          ein neues Ticket.
        </p>
      ) : (
        <form onSubmit={onReply} className="card space-y-3">
          <label htmlFor="reply" className="label">
            Antworten
          </label>
          <textarea
            id="reply"
            required
            minLength={1}
            maxLength={10_000}
            rows={5}
            className="input font-sans"
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            placeholder="Ihre Antwort…"
          />
          <div className="flex gap-3 items-center">
            <button type="submit" className="btn-primary" disabled={posting}>
              {posting ? "Wird gesendet…" : "Antwort senden"}
            </button>
            {canClose && (
              <button
                type="button"
                className="btn-secondary"
                onClick={onClose}
                disabled={closing}
              >
                {closing ? "Wird geschlossen…" : "Ticket schließen"}
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}
