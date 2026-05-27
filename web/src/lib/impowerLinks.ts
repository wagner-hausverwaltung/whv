/// External-link builders for Impower's web app.
///
/// Impower has two contact views — `/persons/view-person/{id}` for
/// natural persons and `/companies/view-company/{id}` for legal
/// entities — selected by the contact's `kind`. Returning `null`
/// when the id is missing keeps callers' optional-chaining tight:
///
///   const href = impowerContactUrl(c.kind, c.impower_id);
///   {href && <Link href={href} target="_blank">…</Link>}
///
/// We intentionally avoid embedding the Impower domain anywhere else
/// in the SPA so a future tenancy / sandbox swap is a one-file edit.

const IMPOWER_WEB_BASE = "https://app.impower.de";

/// Build the right Impower contact-view URL for a (kind, impower_id)
/// pair. Returns null when the id is null/undefined. Unknown kinds
/// fall back to the company view — its URL shape is the same as the
/// person one in practice and the form's "wrong kind" UI is far more
/// forgiving than a 404.
export function impowerContactUrl(
  kind: string | null | undefined,
  impowerId: number | string | null | undefined,
): string | null {
  if (impowerId == null) return null;
  const segment = kind === "PERSON" ? "persons/view-person" : "companies/view-company";
  return `${IMPOWER_WEB_BASE}/${segment}/${impowerId}`;
}
