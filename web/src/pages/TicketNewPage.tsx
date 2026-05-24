import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import {
  TICKET_CATEGORY_LABELS,
  type TicketCategory,
  type TicketDetailResponse,
} from "@/api/types";

const CATEGORIES: TicketCategory[] = [
  "SCHADEN",
  "VERWALTUNG",
  "HAUSGELD",
  "SONSTIGES",
];

export function TicketNewPage() {
  const navigate = useNavigate();
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState<TicketCategory>("SONSTIGES");
  const [body, setBody] = useState("");
  // Sharing defaults to PRIVATE; creator can widen later from the detail page
  // (PARTICIPANTS / PROPERTY). Skipping the property picker for v1 — owners
  // can attach the ticket to a property later via the admin UI or extend here
  // when the property picker becomes available on the portal too.
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await api.post<TicketDetailResponse>("/me/tickets", {
        subject: subject.trim(),
        body: body.trim(),
        category,
      });
      navigate(`/tickets/${res.data.id}`, { replace: true });
    } catch {
      setError(
        "Ticket konnte nicht erstellt werden. Bitte prüfen Sie Ihre Eingaben.",
      );
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h1 className="text-2xl font-bold">Neues Ticket</h1>
        <p className="muted mt-2">
          Schildern Sie Ihr Anliegen — wir melden uns über das Portal und per
          E-Mail.
        </p>
      </div>

      {error && <p className="flash-error">{error}</p>}

      <form onSubmit={onSubmit} className="card space-y-4">
        <div>
          <label htmlFor="subject" className="label">
            Betreff
          </label>
          <input
            id="subject"
            type="text"
            required
            minLength={3}
            maxLength={200}
            className="input"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          />
        </div>

        <div>
          <label htmlFor="category" className="label">
            Kategorie
          </label>
          <select
            id="category"
            className="input"
            value={category}
            onChange={(e) => setCategory(e.target.value as TicketCategory)}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {TICKET_CATEGORY_LABELS[c]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="body" className="label">
            Beschreibung
          </label>
          <textarea
            id="body"
            required
            minLength={3}
            maxLength={10_000}
            rows={8}
            className="input font-sans"
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
        </div>

        <div className="flex gap-3">
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? "Wird gesendet…" : "Ticket erstellen"}
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => navigate("/tickets")}
            disabled={submitting}
          >
            Abbrechen
          </button>
        </div>
      </form>
    </div>
  );
}
