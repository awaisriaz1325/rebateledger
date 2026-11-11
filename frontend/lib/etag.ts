"use client";

/** Optimistic locking helpers: keep the ETag from a GET and send it as If-Match. */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { ApiError, unwrap } from "@/lib/api";

export interface Versioned<T> {
  data: T;
  etag: string;
}

export function useVersioned<T>(key: readonly unknown[], fetcher: () => Promise<{ data?: T; error?: unknown; response: Response }>): UseQueryResult<Versioned<T>> {
  return useQuery({
    queryKey: key,
    queryFn: async () => {
      const result = await fetcher();
      const data = unwrap(result);
      return { data, etag: result.response.headers.get("ETag") ?? "" };
    },
  });
}

export function isConflict(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 412 || error.status === 428);
}
