// Single axios instance with auto-refresh interceptor.
//
// Tradeoff (v1): tokens live in localStorage. XSS-exposed but standard SPA
// pattern. iOS will use Keychain (secure). Web v2 may move refresh into an
// HttpOnly cookie if security review demands it.

import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";

const TOKEN_KEY = "whv.access_token";
const REFRESH_KEY = "whv.refresh_token";

export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(TOKEN_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}
export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}
export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY);
}

const API_BASE_URL =
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (import.meta as any).env?.VITE_API_BASE_URL ?? "/api";

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

// Refresh queue: while one refresh is in flight, queue concurrent failures
// and resolve them with the new token (or reject if refresh ultimately fails).
let refreshInFlight: Promise<string> | null = null;
type Waiter = (token: string | null) => void;
const waiters: Waiter[] = [];

function flushWaiters(token: string | null): void {
  while (waiters.length) {
    const cb = waiters.shift();
    cb?.(token);
  }
}

async function performRefresh(): Promise<string> {
  const refresh = getRefreshToken();
  if (!refresh) throw new Error("no refresh token");

  // Use a fresh axios call (no interceptor recursion).
  const res = await axios.post(
    `${API_BASE_URL}/auth/refresh`,
    { refresh_token: refresh },
    { headers: { "Content-Type": "application/json" } },
  );
  const access = res.data.access_token as string;
  const newRefresh = (res.data.refresh_token as string) ?? refresh;
  setTokens(access, newRefresh);
  return access;
}

api.interceptors.response.use(
  (r) => r,
  async (err: AxiosError) => {
    const original = err.config as InternalAxiosRequestConfig & {
      _retried?: boolean;
    };
    if (
      !original ||
      err.response?.status !== 401 ||
      original._retried ||
      // Don't try to refresh the refresh endpoint itself
      original.url?.endsWith("/auth/refresh")
    ) {
      return Promise.reject(err);
    }

    original._retried = true;

    try {
      if (!refreshInFlight) {
        refreshInFlight = performRefresh()
          .then((token) => {
            flushWaiters(token);
            refreshInFlight = null;
            return token;
          })
          .catch((e) => {
            flushWaiters(null);
            refreshInFlight = null;
            throw e;
          });
      }
      const newToken = await refreshInFlight;
      original.headers.set("Authorization", `Bearer ${newToken}`);
      return api(original);
    } catch {
      clearTokens();
      // Tell the app the user needs to re-auth. Best done via a window event;
      // AuthContext listens and updates state without a full reload.
      window.dispatchEvent(new Event("whv:auth:expired"));
      return Promise.reject(err);
    }
  },
);
