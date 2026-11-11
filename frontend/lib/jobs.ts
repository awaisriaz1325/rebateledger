"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api, unwrap } from "@/lib/api";

const DONE = new Set(["succeeded", "failed", "cancelled", "dead"]);

/**
 * Poll a background job until it finishes (202 + job resource pattern, SPEC §6).
 * `onDone` fires once per job id, after the server reports a terminal status.
 */
export function useJob(jobId: string | null | undefined, onDone?: (status: string) => void) {
  const query = useQuery({
    queryKey: ["job", jobId],
    enabled: !!jobId,
    queryFn: async () => unwrap(await api.GET("/api/v1/jobs/{job_id}", { params: { path: { job_id: jobId ?? "" } } })),
    refetchInterval: (q) => (q.state.data && DONE.has(q.state.data.status) ? false : 1000),
  });
  const fired = useRef<string | null>(null);
  const callback = useRef(onDone);
  useEffect(() => {
    callback.current = onDone;
  });
  const status = query.data?.status;
  useEffect(() => {
    if (jobId && status && DONE.has(status) && fired.current !== jobId) {
      fired.current = jobId;
      callback.current?.(status);
    }
  }, [jobId, status]);
  return query;
}

export function jobDone(status: string | undefined): boolean {
  return !!status && DONE.has(status);
}
