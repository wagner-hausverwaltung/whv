/**
 * Remembers which Liegenschaft the user last looked at.
 *
 * The active property is normally read straight off the URL
 * (/properties/:id/*). But the global routes — /tickets, /resolutions,
 * /settings — carry no property id, so without a memory the AppBar
 * switcher (and the root redirect) would fall back to "the first
 * property in the list" and visibly snap away from the one the user
 * had selected. We persist the last URL-derived id in localStorage and
 * fall back to it on those id-less routes instead.
 *
 * localStorage (not sessionStorage) so the choice also survives a full
 * reload / new tab — matching the iOS app, which remembers the active
 * Liegenschaft across launches.
 */

const STORAGE_KEY = "whv.activePropertyId";

export function getRememberedPropertyId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    // Private-mode / disabled storage — degrade to "no memory".
    return null;
  }
}

export function rememberPropertyId(id: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Ignore — persistence is a nicety, not a correctness requirement.
  }
}
