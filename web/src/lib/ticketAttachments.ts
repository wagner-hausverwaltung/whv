import type { AxiosError } from "axios";
import { API_BASE_URL, getAccessToken } from "@/api/client";
import type { TicketMessageAttachmentResponse } from "@/api/types";

/** Turn whatever an axios `.catch(err)` produces into a short, human
 *  diagnostic string. The reply form renders this verbatim under the
 *  filename, so it has to be tight + useful for both the user and us
 *  (when they paste it back as a bug report).
 *
 *  Priorities, in order:
 *    1. FastAPI's `detail` field if present (most actionable).
 *    2. HTTP status mapped to a plain-language hint when known
 *       (413 → size cap, 404 → endpoint missing, 401 → auth, 0 → CORS).
 *    3. Raw status + abridged response body as a last resort.
 *    4. The axios `message` for total network failures.
 *
 *  Kept tiny and dependency-free so it can be reused outside the
 *  ticket-attachments surface (e.g. document uploads) later.
 */
export function describeUploadError(err: unknown): string {
  const axErr = err as AxiosError<{ detail?: string } | string>;
  const status = axErr.response?.status;
  const data = axErr.response?.data;

  // 1. FastAPI / our endpoints always carry `detail` on user-facing errors.
  if (data && typeof data === "object" && data.detail) {
    return data.detail;
  }

  // 2. Known status-code hints.
  if (status === 401 || status === 403) {
    return "Authentifizierung abgelaufen. Bitte erneut anmelden.";
  }
  if (status === 404) {
    return "Upload-Endpoint nicht gefunden (404) — Backend-Deploy noch ausstehend?";
  }
  if (status === 413) {
    return "Datei zu groß (413). Bitte verkleinern und erneut versuchen.";
  }
  if (status === 415) {
    return "Dateityp nicht unterstützt (415).";
  }
  if (status && status >= 500) {
    return `Serverfehler (${status}). Bitte später erneut versuchen.`;
  }

  // 3. Status + abridged body.
  if (status) {
    const body =
      typeof data === "string" ? data.slice(0, 120) : JSON.stringify(data ?? "").slice(0, 120);
    return `HTTP ${status}${body ? ` — ${body}` : ""}`;
  }

  // 4. No response at all — CORS preflight, DNS, or network. axios
  // sets a `code` like "ERR_NETWORK" but it's not localised, so we
  // bias toward the most likely staging cause.
  return "Netzwerkfehler — Server nicht erreichbar oder CORS abgelehnt.";
}

/** Authenticated download via blob URL.
 *
 *  We can't drop a plain `<a href>` against the file endpoint — the
 *  browser won't attach our JWT — so we fetch the bytes with the right
 *  header and synthesise a click on a temporary blob URL. Same pattern
 *  used in `DocumentFoldersPanel`. Lives in `lib/` (not next to the
 *  React component) so React's fast-refresh rule stays happy.
 */
export async function downloadAttachment(
  ticketId: string,
  attachment: TicketMessageAttachmentResponse,
  scope: "admin" | "portal",
): Promise<void> {
  const base = scope === "admin" ? "/admin" : "/me";
  const token = getAccessToken();
  const res = await fetch(
    `${API_BASE_URL}${base}/tickets/${ticketId}/attachments/${attachment.id}/file`,
    token ? { headers: { Authorization: `Bearer ${token}` } } : undefined,
  );
  if (!res.ok) throw new Error(`${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = attachment.filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Tiny delay so Safari finishes the download before the URL dies.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
