import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, API_BASE_URL } from "@/api/client";
import {
  RESOLUTION_MODE_LABELS,
  RESOLUTION_STATUS_LABELS,
  VOTE_CHOICE_LABELS,
  type ResolutionDetailResponse,
  type VoteChoice,
} from "@/api/types";

function StatusBadge({
  status,
}: {
  status: ResolutionDetailResponse["status"];
}) {
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

function ChoiceButton({
  label,
  active,
  onClick,
  disabled,
  tone,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  disabled: boolean;
  tone: "green" | "red" | "neutral";
}) {
  const baseTone =
    tone === "green"
      ? active
        ? "bg-emerald-600 text-white border-emerald-600"
        : "border-emerald-200 text-emerald-900 hover:bg-emerald-50"
      : tone === "red"
        ? active
          ? "bg-red-600 text-white border-red-600"
          : "border-red-200 text-red-900 hover:bg-red-50"
        : active
          ? "bg-slate-700 text-white border-slate-700"
          : "border-slate-200 text-slate-700 hover:bg-slate-50";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`px-4 py-2 rounded border font-medium transition-colors disabled:opacity-50 ${baseTone}`}
    >
      {label}
    </button>
  );
}

export function ResolutionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [resolution, setResolution] = useState<ResolutionDetailResponse | null>(
    null,
  );
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voting, setVoting] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const refresh = async () => {
    if (!id) return;
    try {
      const r = await api.get<ResolutionDetailResponse>(`/me/resolutions/${id}`);
      setResolution(r.data);
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } }).response
        ?.status;
      if (httpStatus === 404) setNotFound(true);
      else setError("Beschluss konnte nicht geladen werden.");
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/exhaustive-deps, react-hooks/set-state-in-effect
    void refresh();
  }, [id]);

  const castVote = async (choice: VoteChoice) => {
    if (!id || voting) return;
    setVoting(true);
    setError(null);
    try {
      await api.post(`/me/resolutions/${id}/vote`, { choice });
      setFlash(`Ihre Stimme (${VOTE_CHOICE_LABELS[choice]}) wurde gespeichert.`);
      await refresh();
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } }).response
        ?.status;
      setError(
        httpStatus === 400
          ? "Abstimmung ist nicht (mehr) offen."
          : "Stimme konnte nicht gespeichert werden.",
      );
    } finally {
      setVoting(false);
    }
  };

  if (notFound) {
    return (
      <div className="space-y-4">
        <p className="flash-error">
          Beschluss nicht gefunden oder nicht zugänglich.
        </p>
        <Link to="/resolutions" className="muted">
          ← Zurück zur Übersicht
        </Link>
      </div>
    );
  }
  if (error && !resolution) return <p className="flash-error">{error}</p>;
  if (resolution === null) return <p className="muted">Wird geladen…</p>;

  const t = resolution.tally;
  const isOpen = resolution.status === "OFFEN";
  const myChoice = resolution.my_vote?.choice ?? null;

  return (
    <div className="space-y-6">
      <div>
        <Link to="/resolutions" className="muted">
          ← Beschlüsse
        </Link>
      </div>

      <header className="space-y-2">
        <h1 className="text-2xl font-bold">{resolution.title}</h1>
        <div className="muted">
          <StatusBadge status={resolution.status} /> ·{" "}
          {RESOLUTION_MODE_LABELS[resolution.mode]} · Frist{" "}
          {new Date(resolution.closes_at).toLocaleString("de-DE")}
        </div>
      </header>

      {flash && <p className="flash-success">{flash}</p>}
      {error && resolution && <p className="flash-error">{error}</p>}

      <section className="card">
        <h2 className="text-lg font-semibold mb-2">Beschlusstext</h2>
        <div className="whitespace-pre-wrap text-sm leading-relaxed">
          {resolution.description}
        </div>
      </section>

      {resolution.am_eligible && isOpen && (
        <section className="card">
          <h2 className="text-lg font-semibold mb-3">Ihre Stimme</h2>
          {myChoice ? (
            <p className="muted mb-3">
              Sie haben bereits mit{" "}
              <strong>{VOTE_CHOICE_LABELS[myChoice]}</strong> abgestimmt. Sie
              können Ihre Stimme bis zur Frist ändern.
            </p>
          ) : (
            <p className="muted mb-3">
              Wählen Sie eine Option. Sie können Ihre Stimme bis zur Frist
              ändern.
            </p>
          )}
          <div className="flex gap-3">
            <ChoiceButton
              label="JA"
              tone="green"
              active={myChoice === "JA"}
              disabled={voting}
              onClick={() => castVote("JA")}
            />
            <ChoiceButton
              label="NEIN"
              tone="red"
              active={myChoice === "NEIN"}
              disabled={voting}
              onClick={() => castVote("NEIN")}
            />
            <ChoiceButton
              label="Enthaltung"
              tone="neutral"
              active={myChoice === "ENTHALTUNG"}
              disabled={voting}
              onClick={() => castVote("ENTHALTUNG")}
            />
          </div>
        </section>
      )}

      {resolution.am_eligible && !isOpen && resolution.my_vote && (
        <section className="card">
          <h2 className="text-lg font-semibold mb-2">Ihre abgegebene Stimme</h2>
          <p>
            <strong>{VOTE_CHOICE_LABELS[resolution.my_vote.choice]}</strong>{" "}
            <span className="muted">
              · abgegeben{" "}
              {new Date(resolution.my_vote.voted_at).toLocaleString("de-DE")}
            </span>
          </p>
        </section>
      )}

      <section className="card">
        <h2 className="text-lg font-semibold mb-3">Stand der Abstimmung</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
          <div>
            <div className="muted">Stimmberechtigt</div>
            <div className="text-2xl font-semibold">{t.eligible_voters}</div>
          </div>
          <div>
            <div className="muted">Abgegeben</div>
            <div className="text-2xl font-semibold">{t.cast}</div>
          </div>
          {resolution.mode === "MEHRHEITS" && (
            <div>
              <div className="muted">Erforderliches Quorum</div>
              <div className="text-2xl font-semibold">
                {resolution.required_quorum}
              </div>
            </div>
          )}
        </div>
        {resolution.status !== "OFFEN" && (
          <div className="grid grid-cols-3 gap-3 text-sm mt-4">
            <div>
              <div className="muted">JA</div>
              <div className="text-2xl font-semibold text-emerald-700">
                {t.ja}
              </div>
            </div>
            <div>
              <div className="muted">NEIN</div>
              <div className="text-2xl font-semibold text-red-700">
                {t.nein}
              </div>
            </div>
            <div>
              <div className="muted">Enthaltung</div>
              <div className="text-2xl font-semibold text-slate-700">
                {t.enthaltung}
              </div>
            </div>
          </div>
        )}
        {resolution.result && (
          <p className="mt-4 text-sm">
            <strong>Ergebnis:</strong> {resolution.result}
          </p>
        )}
        {resolution.result_pdf_url && (
          <p className="mt-3">
            <a
              href={`${API_BASE_URL}/me/resolutions/${resolution.id}/result.pdf`}
              className="text-whv-blue underline"
            >
              Protokoll-PDF herunterladen
            </a>
          </p>
        )}
      </section>
    </div>
  );
}
