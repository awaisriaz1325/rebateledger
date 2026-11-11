"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/ui/core";
import { StatusBadge } from "@/components/ui/finance";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { can, useSession } from "@/lib/session";

export default function ImportsPage() {
  const session = useSession();
  const router = useRouter();
  const query = useQuery({ queryKey: ["imports"], queryFn: async () => unwrap(await api.GET("/api/v1/imports", { params: { query: { limit: 200 } } })).items });
  const add = can(session, "manage_imports") ? <Link href="/app/imports/new" className="inline-flex h-9 items-center rounded-md bg-brand px-4 text-sm font-medium text-on-brand">New import</Link> : null;
  return (
    <>
      <PageHeader title="Imports" description="Purchase lines, supplier credits, baselines, products and suppliers from your ERP exports (CSV or XLSX)." actions={add} />
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No imports yet" action={add}>Upload a purchase export to get started.</EmptyState>}>
        {(rows) => (
          <DataTable label="Imports" rows={rows} rowKey={(r) => r.id} exportName="import-history" onRowClick={(r) => router.push(`/app/imports/${r.id}`)}
            columns={[
              { id: "file", header: "File", value: (r) => r.filename, cell: (r) => <Link className="font-medium hover:underline" href={`/app/imports/${r.id}`}>{r.filename}</Link> },
              { id: "type", header: "Type", value: (r) => r.import_type },
              { id: "status", header: "Status", value: (r) => r.status, cell: (r) => <StatusBadge status={r.status} /> },
              { id: "rows", header: "Rows committed", value: (r) => String(r.stats.rows_committed ?? ""), align: "right", numeric: true },
              { id: "from", header: "Data from", value: (r) => String(r.stats.date_from ?? "") },
              { id: "to", header: "Data to", value: (r) => String(r.stats.date_to ?? "") },
              { id: "uploaded", header: "Uploaded", value: (r) => r.created_at, cell: (r) => formatDateTime(r.created_at) },
            ]} />
        )}
      </QueryState>
    </>
  );
}
