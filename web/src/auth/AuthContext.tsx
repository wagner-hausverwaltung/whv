import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, clearTokens, getAccessToken, setTokens } from "@/api/client";
import type { UserResponse } from "@/api/types";

interface AuthState {
  user: UserResponse | null;
  loading: boolean;
}
interface AuthValue extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    loading: Boolean(getAccessToken()),
  });

  const refreshMe = useCallback(async () => {
    if (!getAccessToken()) {
      setState({ user: null, loading: false });
      return;
    }
    try {
      const me = await api.get<UserResponse>("/me");
      setState({ user: me.data, loading: false });
    } catch {
      clearTokens();
      setState({ user: null, loading: false });
    }
  }, []);

  useEffect(() => {
    // Bootstrap: if a token is in localStorage, validate it by calling /me.
    // refreshMe() internally setState's user/loading — this is the
    // canonical "initial fetch on mount" pattern.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshMe();
    const onExpired = () => setState({ user: null, loading: false });
    window.addEventListener("whv:auth:expired", onExpired);
    return () => window.removeEventListener("whv:auth:expired", onExpired);
  }, [refreshMe]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.post("/auth/login", { email, password });
    setTokens(res.data.access_token, res.data.refresh_token);
    setState({ user: res.data.user, loading: false });
  }, []);

  const logout = useCallback(async () => {
    const refresh = localStorage.getItem("whv.refresh_token");
    if (refresh) {
      try {
        await api.post("/auth/logout", { refresh_token: refresh });
      } catch {
        // Best-effort — proceed to clear local state regardless.
      }
    }
    clearTokens();
    setState({ user: null, loading: false });
  }, []);

  const value = useMemo<AuthValue>(
    () => ({ ...state, login, logout, refreshMe }),
    [state, login, logout, refreshMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be inside <AuthProvider>");
  return ctx;
}
