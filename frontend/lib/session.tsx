"use client";

/** Session state from GET /api/v1/auth/session (cookie-based, HttpOnly). */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";
import { api, setCsrfToken, unwrap } from "@/lib/api";
import type { components } from "@/generated/api";

export type SessionInfo = components["schemas"]["SessionInfo"];

export const SESSION_KEY = ["session"] as const;

export function useSessionQuery() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: async () => {
      const s = unwrap(await api.GET("/api/v1/auth/session"));
      setCsrfToken(s.csrf_token);
      return s;
    },
    staleTime: 60_000,
  });
}

const SessionContext = createContext<SessionInfo | null>(null);

export function SessionProvider({ value, children }: { value: SessionInfo; children: ReactNode }) {
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionInfo {
  const s = useContext(SessionContext);
  if (!s) throw new Error("useSession must be used inside SessionProvider");
  return s;
}

export function can(session: SessionInfo, permission: string): boolean {
  return session.organization?.permissions.includes(permission) ?? false;
}

export function useRefreshSession() {
  const qc = useQueryClient();
  return (next?: SessionInfo) => {
    if (next) {
      setCsrfToken(next.csrf_token);
      qc.setQueryData(SESSION_KEY, next);
    }
    return qc.invalidateQueries();
  };
}
