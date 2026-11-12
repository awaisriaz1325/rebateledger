"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { DataTable } from "@/components/data-table";
import { Button, Field, PageHeader, Select } from "@/components/ui/core";
import { StatusBadge } from "@/components/ui/finance";
import { QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { paths } from "@/generated/api";

type StatusFilter = NonNullable<NonNullable<paths["/api/v1/ops/jobs"]["get"]["parameters"]["query"]>["status"]>;

export default function OpsJobsPage() {
  const qc = useQueryClient();
  const [status, setStatus] = useState<StatusFilter | "">("");
  const query = useQuery({
    queryKey: ["ops", "jobs", status],
    queryFn: async () => unwrap(await api.GET("/api/v1/ops/jobs", { params: { query: { status: status || undefined } } })),
    refetchInterval: 5000,
  });
  const retry = useMutation({
    mutationFn: async (id: string) => unwrap(await api.POST("/api/v1/ops/jobs/{job_id}/retry", { params: { path: { job_id: id } } })),
    onSuccess: () => { toast.success("Job queued again"); void qc.invalidateQueries({ queryKey: ["ops", "jobs"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <>
      <PageHeader title="Jobs" description="Background work across all organizations. Payloads are never shown (they may contain sealed email content)." />
      <QueryState query={query}>
        {(o) => (
          <>
            <dl className="mb-4 flex flex-wrap gap-6 text-sm">
              {Object.entries(o.counts).map(([k, v]) => <div key={k}><dt className="text-xs text-muted capitalize">{k}</dt><dd className={`text-lg font-semibold ${k === "dead" && v > 0 ? "text-negative" : ""}`}>{v}</dd></div>)}
            </dl>
            <Field id="j-status" label="Show" className="mb-3 max-w-48">
              <Select id="j-status" value={status} onChange={(e) => setStatus(e.target.value as StatusFilter | "")}>
                <option value="">Latest 100</option>
                {Object.keys(o.counts).map((k) => <option key={k} value={k}>{k}</option>)}
              </Select>
            </Field>
            <DataTable
              label="Jobs"
              rows={o.jobs}
              rowKey={(j) => j.id}
              columns={[
                { id: "type", header: "Type", value: (j) => j.type, cell: (j) => <span className="font-mono text-xs">{j.type}</span> },
                { id: "status", header: "Status", value: (j) => j.status, cell: (j) => <StatusBadge status={j.status} /> },
                { id: "attempts", header: "Attempts", value: (j) => `${j.attempts}/${j.max_attempts}` },
                { id: "error", header: "Error", value: (j) => String(j.error?.message ?? ""), cell: (j) => <span className="line-clamp-1 max-w-sm text-xs text-muted">{String(j.error?.message ?? "")}</span> },
                { id: "created", header: "Created", value: (j) => j.created_at, cell: (j) => formatDateTime(j.created_at) },
                { id: "retry", header: "", value: () => "", cell: (j) => (j.status === "dead" || j.status === "failed" ? <Button size="sm" variant="secondary" onClick={() => retry.mutate(j.id)}>Retry</Button> : null) },
              ]}
            />
          </>
        )}
      </QueryState>
    </>
  );
}
