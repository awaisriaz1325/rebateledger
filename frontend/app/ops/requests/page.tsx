"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { PageHeader, Select } from "@/components/ui/core";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { components } from "@/generated/api";

type Status = NonNullable<components["schemas"]["PilotPatch"]["status"]>;
const STATUSES: Status[] = ["new", "contacted", "converted", "declined", "spam"];

export default function OpsRequestsPage() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["ops", "pilots"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/pilot-requests")) });
  const update = useMutation({
    mutationFn: async ({ id, status }: { id: string; status: Status }) => unwrap(await api.PATCH("/api/v1/ops/pilot-requests/{request_id}", { params: { path: { request_id: id } }, body: { status } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["ops", "pilots"] }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <>
      <PageHeader title="Pilot requests" description="Submissions from the website's request-a-pilot form." />
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No requests yet" />}>
        {(rows) => (
          <ul className="flex flex-col gap-3">
            {rows.map((p) => (
              <li key={p.id} className="rounded-lg border border-rule bg-surface p-4 text-sm">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-medium">{p.company} · {p.name}{p.role ? `, ${p.role}` : ""}</p>
                    <p className="text-xs text-muted"><a className="underline" href={`mailto:${p.email}`}>{p.email}</a> · {formatDateTime(p.created_at)}{p.supplier_count ? ` · ${p.supplier_count} suppliers` : ""}</p>
                  </div>
                  <label className="flex items-center gap-2 text-xs">
                    <span className="sr-only">Status for {p.company}</span>
                    <Select value={p.status} onChange={(e) => update.mutate({ id: p.id, status: e.target.value as Status })} className="h-8">
                      {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                    </Select>
                  </label>
                </div>
                {p.message ? <p className="mt-2 whitespace-pre-wrap">{p.message}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </>
  );
}
