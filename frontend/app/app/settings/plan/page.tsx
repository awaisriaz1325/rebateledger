"use client";

import { useQuery } from "@tanstack/react-query";
import { StatusBadge } from "@/components/ui/finance";
import { Card } from "@/components/ui/core";
import { QueryState } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";

const LABELS: Record<string, [string, string]> = {
  max_active_agreements: ["Active agreements", "active_agreements"],
  max_users: ["Users", "users"],
  max_import_rows_per_month: ["Imported rows this month", "import_rows_this_month"],
  max_storage_mb: ["Stored files (MB)", "storage_mb"],
};

export default function PlanPage() {
  const query = useQuery({ queryKey: ["plan"], queryFn: async () => unwrap(await api.GET("/api/v1/org/plan")) });
  return (
    <Card title="Plan & usage">
      <QueryState query={query}>
        {(p) => (
          <>
            {p.plan_name ? (
              <p className="mb-4 text-sm">Plan: <strong>{p.plan_name}</strong> {p.status ? <StatusBadge status={p.status} /> : null}</p>
            ) : (
              <p className="mb-4 text-sm text-muted">No plan is assigned yet; your account manager sets this up.</p>
            )}
            <dl className="grid max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
              {Object.entries(LABELS).map(([limitKey, [label, usageKey]]) => {
                const used = p.usage[usageKey] ?? 0;
                const limit = p.limits[limitKey];
                return (
                  <div key={limitKey} className="rounded-md border border-rule p-3">
                    <dt className="text-xs text-muted">{label}</dt>
                    <dd className="num mt-1 text-left text-lg font-semibold">{used.toLocaleString("en-US")}{limit != null ? <span className="text-sm font-normal text-muted"> of {limit.toLocaleString("en-US")}</span> : null}</dd>
                  </div>
                );
              })}
            </dl>
            <p className="mt-4 text-xs text-muted">Limits block only new actions; existing data always stays available. Invoices appear here once billing is set up.</p>
          </>
        )}
      </QueryState>
    </Card>
  );
}
