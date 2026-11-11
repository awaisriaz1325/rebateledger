"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/ui/core";
import { StatusBadge } from "@/components/ui/finance";
import { EmptyState, QueryState } from "@/components/ui/states";
import { fetchAllAgreements, fetchAllSuppliers } from "@/lib/queries";
import { can, useSession } from "@/lib/session";

export default function AgreementsPage() {
  const session = useSession();
  const router = useRouter();
  const query = useQuery({
    queryKey: ["agreements", "all"],
    queryFn: async () => {
      const [agreements, suppliers] = await Promise.all([fetchAllAgreements(), fetchAllSuppliers()]);
      const names = new Map(suppliers.map((s) => [s.id, s.name]));
      return agreements.map((a) => ({ ...a, supplier_name: names.get(a.supplier_id) ?? "" }));
    },
  });
  const add = can(session, "edit_agreements") ? <Link href="/app/agreements/new" className="inline-flex h-9 items-center rounded-md bg-brand px-4 text-sm font-medium text-on-brand">New agreement</Link> : null;
  return (
    <>
      <PageHeader title="Agreements" description="Rebate programs as precise, versioned rules. Active versions never change; new terms get a new version." actions={add} />
      <QueryState query={query} isEmpty={(a) => a.length === 0} empty={<EmptyState title="No agreements yet" action={add}>Add a rebate program from a supplier contract.</EmptyState>}>
        {(rows) => (
          <DataTable
            label="Agreements"
            rows={rows}
            rowKey={(r) => r.id}
            exportName="agreements"
            onRowClick={(r) => router.push(`/app/agreements/${r.id}`)}
            columns={[
              { id: "name", header: "Agreement", value: (r) => r.name, cell: (r) => <Link href={`/app/agreements/${r.id}`} className="font-medium hover:underline">{r.name}</Link> },
              { id: "supplier", header: "Supplier", value: (r) => r.supplier_name },
              { id: "ref", header: "Reference", value: (r) => r.external_reference ?? "", cell: (r) => <span className="font-mono text-xs">{r.external_reference}</span> },
              { id: "version", header: "Active version", value: (r) => r.active_version ?? "", align: "right" },
              { id: "state", header: "Latest version", value: (r) => r.latest_version_status ?? "", cell: (r) => (r.status === "archived" ? <StatusBadge status="archived" /> : r.latest_version_status ? <StatusBadge status={r.latest_version_status} /> : null) },
              { id: "summary", header: "Summary", value: (r) => r.summary, cell: (r) => <span className="line-clamp-1 max-w-md text-xs text-muted">{r.summary}</span>, hidden: false },
            ]}
          />
        )}
      </QueryState>
    </>
  );
}
