"use client";

/** Helpers shared by forms: zod resolver + mapping server Problem Details onto fields. */
import { zodResolver } from "@hookform/resolvers/zod";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { ApiError, errorMessage } from "@/lib/api";

export { zodResolver };

/** Server validation is the authority: show its field errors, return a form-level message. */
export function applyServerErrors<T extends FieldValues>(error: unknown, setError: UseFormSetError<T>, fields: readonly string[]): string | null {
  if (error instanceof ApiError) {
    const byField = error.fieldErrors();
    let mapped = false;
    for (const [field, message] of Object.entries(byField)) {
      if (fields.includes(field)) {
        setError(field as Path<T>, { type: "server", message });
        mapped = true;
      }
    }
    if (mapped && !error.problem.detail) return null;
    return error.problem.detail || error.problem.title;
  }
  return errorMessage(error);
}

/** Read a one-time token from the email link (captured once), then remove it from the address bar. */
export function useLinkToken(): string | null {
  const params = useSearchParams();
  const [token] = useState<string | null>(() => params.get("token"));
  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.has("token")) {
      url.searchParams.delete("token");
      window.history.replaceState(null, "", url.pathname + url.search);
    }
  }, []);
  return token;
}

/** Only allow same-site relative redirects after sign-in (no open redirects). */
export function safeNext(next: string | null): string {
  if (next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")) return next;
  return "/app";
}
