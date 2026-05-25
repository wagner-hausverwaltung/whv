/**
 * Heuristic signature / quoted-reply trimmer for ticket message bodies.
 *
 * Tickets arrive both from the SPA reply form (clean) and from email
 * inbound (Outlook + Apple Mail + Gmail all pile boilerplate at the
 * bottom: salutation line, image alt text, phone / address card,
 * compliance footer, sometimes a quoted previous thread). The full
 * body stays in the database and on the wire — we only trim the
 * default render so the reader doesn't have to scroll past 30 lines
 * of vCard to get to the next message.
 *
 * Strategy: walk the body line-by-line; first match of either
 *   • a salutation line ("Viele Grüße!", "Best regards", "-- ", …)
 *   • a reply header ("Am 25.5.2026 schrieb …:", "From: ...", …)
 * becomes the cut point. Salutations stay in the visible half (it'd
 * feel rude to hide the closing line); reply headers do not (they're
 * pure noise above the quoted prior thread).
 *
 * Returns the visible slice plus how many trailing lines were hidden
 * so the UI can decide whether the toggle is worth showing. We bail
 * (return the full body untouched) if the trim would leave an empty
 * visible half or only hides ≤1 line — not worth the chrome.
 */

// Match a salutation. Includes both the closing line ("Viele Grüße!")
// and the RFC 3676 sig separator. Tested against Outlook, Apple Mail,
// Gmail, and a handful of hand-typed Verwalter replies.
const SALUTATION_RE: RegExp[] = [
  // Standard RFC 3676 / Mutt-style sig delimiter — two dashes + space.
  /^--\s?$/,
  // German salutations. "Grüße" / "Grüßen" both ok; some folks write
  // "Gruesse" without the ß; period / exclamation / comma allowed.
  /^(viele|beste|liebe|herzliche)\s+gr(ü|ue?)(ß|ss)e[!.,]?\s*$/i,
  /^mit\s+(freundlichen|besten|liebsten|lieben|herzlichen)\s+gr(ü|ue?)(ß|ss)en[!.,]?\s*$/i,
  /^freundliche\s+gr(ü|ue?)(ß|ss)e[!.,]?\s*$/i,
  /^gr(ü|ue?)(ß|ss)(e|en)?[!.,]?\s*$/i,
  /^hochachtungsvoll[!.,]?\s*$/i,
  /^m\.?\s*f\.?\s*g\.?[!.,]?\s*$/i,
  /^vg[!.,]?\s*$/i,
  // English salutations.
  /^(best|kind|warm)\s+regards[!.,]?\s*$/i,
  /^regards[!.,]?\s*$/i,
  /^cheers[!.,]?\s*$/i,
  /^yours\s+(sincerely|truly|faithfully)[!.,]?\s*$/i,
  /^sincerely[!.,]?\s*$/i,
  /^thanks[!.,]?\s*$/i,
  /^thank you[!.,]?\s*$/i,
  // Auto-footers from mobile mail clients.
  /^sent\s+from\s+my\s+(iphone|ipad|android|smartphone|handy)/i,
  /^von\s+meinem\s+(iphone|ipad|android|handy)/i,
];

// Match a reply / forward header. These open the quoted previous
// thread; nothing useful follows in 99 % of cases.
const REPLY_HEADER_RE: RegExp[] = [
  // Outlook / Apple Mail "Am 25.5.2026 um 09:41 schrieb Luis Wagner:"
  /^am\s+.{3,80}\s+schrieb\s+.+:?\s*$/i,
  // English "On 25 May 2026, at 09:41, Luis Wagner wrote:"
  /^on\s+.{3,80}\s+(wrote|schrieb):?\s*$/i,
  // Outlook reply block header.
  /^(von|from):\s*\S+/i,
  // Gmail-style "----- Original Message -----"
  /^-{3,}\s*original\s+(message|nachricht)\s*-{3,}\s*$/i,
];

export interface SplitResult {
  /** Body up to (and including) the salutation line. May equal `full`. */
  visible: string;
  /** How many lines after the cut were hidden. 0 => no trim happened. */
  hiddenCount: number;
  /** Echo of the input — kept here so callers don't need to re-pass it. */
  full: string;
}

export function splitOnSignature(body: string): SplitResult {
  const lines = body.split(/\r?\n/);
  // Need at least 3 lines for trimming to feel honest — anything
  // shorter probably IS the message.
  if (lines.length < 3) return { visible: body, hiddenCount: 0, full: body };

  // Require at least one non-empty content line before the cut, so we
  // never silently hide an entire single-line message.
  let sawContent = false;
  let cutIdx = -1;
  let includeCutLine = true;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? "";
    const trimmed = line.trim();

    if (!sawContent && trimmed.length > 0) {
      // Salutations / reply headers right at the top mean this *is*
      // the message — don't cut.
      const looksLikeSig =
        SALUTATION_RE.some((r) => r.test(trimmed)) ||
        REPLY_HEADER_RE.some((r) => r.test(trimmed));
      if (!looksLikeSig) sawContent = true;
      if (!sawContent) continue;
    }

    if (!sawContent) continue;

    if (SALUTATION_RE.some((r) => r.test(trimmed))) {
      cutIdx = i;
      includeCutLine = true;
      break;
    }
    if (REPLY_HEADER_RE.some((r) => r.test(trimmed))) {
      cutIdx = i;
      includeCutLine = false;
      break;
    }
  }

  if (cutIdx === -1) return { visible: body, hiddenCount: 0, full: body };

  const sliceEnd = includeCutLine ? cutIdx + 1 : cutIdx;
  const visible = lines.slice(0, sliceEnd).join("\n").replace(/\s+$/u, "");
  const hiddenCount = lines.length - sliceEnd;

  // If the hidden tail is trivial, the toggle would be noise — show full.
  if (hiddenCount <= 1 || visible.trim().length === 0) {
    return { visible: body, hiddenCount: 0, full: body };
  }

  return { visible, hiddenCount, full: body };
}
