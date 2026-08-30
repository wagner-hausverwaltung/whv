import { isAxiosError } from "axios";

/**
 * Minimum password length — MUST match the backend's
 * `Field(min_length=10)` in app/schemas/auth.py (invite redeem + password
 * reset). The portal used to say 8 here: the form accepted a 9-character
 * password, the API answered 422, and the page blamed the invite ("ungültig
 * oder abgelaufen"), so owners retried the same password forever instead of
 * being told to pick a longer one (prod support case B42, 2026-08-25).
 */
export const MIN_PASSWORD_LENGTH = 10;

export const PASSWORD_HINT = `Mindestens ${MIN_PASSWORD_LENGTH} Zeichen.`;

export const PASSWORD_TOO_SHORT = `Passwort muss mindestens ${MIN_PASSWORD_LENGTH} Zeichen lang sein.`;

/** Client-side check mirroring the backend rule; null when the password is fine. */
export function passwordError(password: string, confirm: string): string | null {
  if (password !== confirm) return "Passwörter stimmen nicht überein.";
  if (password.length < MIN_PASSWORD_LENGTH) return PASSWORD_TOO_SHORT;
  return null;
}

/**
 * A 422 from an auth endpoint is always body validation — in practice the
 * password rule. Say that instead of the endpoint's generic failure text,
 * which would send the user down the wrong path.
 */
export function isValidationError(err: unknown): boolean {
  return isAxiosError(err) && err.response?.status === 422;
}
