"use client";

import { useQuery } from "@tanstack/react-query";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/ui/core";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export default function OpsAuditPage() {
  const query = useQuery({ queryKey: ["ops", "audit"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/audit")) });
  return (
    <>
      <PageHeader title="Operator audit" description="Every platform-admin action (hash-chained). Actions inside an organization during support sessions also appear in that organization's own audit log." />
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No operator actions yet" />}>
        {(rows) => (
          <DataTable
            label="Operator audit"
            rows={rows}
            rowKey={(r) => r.id}
            exportName="operator-audit"
            columns={[
              { id: "when", header: "When", value: (r) => r.occurred_at, cell: (r) => formatDateTime(r.occurred_at) },
              { id: "who", header: "Who", value: (r) => r.actor_label },
              { id: "action", header: "Action", value: (r) => r.action, cell: (r) => <span className="font-mono text-xs">{r.action}</span> },
              { id: "object", header: "Object", value: (r) => `${r.object_type} ${r.object_id}`, cell: (r) => <span className="text-xs text-muted">{r.object_type} {r.object_id.slice(0, 8)}</span> },
            ]}
          />
        )}
      </QueryState>
    </>
  );
}
