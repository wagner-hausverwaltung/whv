import { API_BASE_URL, getAccessToken } from "@/api/client";
import type { TicketMessageAttachmentResponse } from "@/api/types";

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
