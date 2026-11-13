"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DataTable } from "@/components/data-table";
import { StatusBadge } from "@/components/ui/finance";
import { PageHeader } from "@/components/ui/core";
import { EmptyState, QueryState } from "@/components/ui/states";
import { can, useSession } from "@/lib/session";
import { fetchAllSuppliers } from "@/lib/queries";

export default function SuppliersPage() {
  const session = useSession();
  const router = useRouter();
  const query = useQuery({ queryKey: ["suppliers", "all"], queryFn: fetchAllSuppliers });
  const add = can(session, "edit_suppliers") ? <Link href="/app/suppliers/new" className="inline-flex h-9 items-center rounded-md bg-brand px-4 text-sm font-medium text-on-brand">Add supplier</Link> : null;
  return (
    <>
      <PageHeader title="Suppliers" description="Manufacturers and vendors you buy from, with the codes they use in your files." actions={add} />
      <QueryState query={query} isEmpty={(s) => s.length === 0} empty={<EmptyState title="No suppliers yet" action={add}>Add your first supplier, or import a supplier list.</EmptyState>}>
        {(rows) => (
          <DataTable
            label="Suppliers"
            rows={rows}
            rowKey={(r) => r.id}
            exportName="suppliers"
            onRowClick={(r) => router.push(`/app/suppliers/${r.id}`)}
            columns={[
              { id: "name", header: "Name", value: (r) => r.name, cell: (r) => <Link href={`/app/suppliers/${r.id}`} className="font-medium hover:underline">{r.name}</Link> },
              { id: "kind", header: "Type", value: (r) => (r.kind === "buying_group" ? "Buying group" : "Supplier") },
              { id: "codes", header: "Codes", value: (r) => r.codes.join(", "), cell: (r) => <span className="font-mono text-xs">{r.codes.join(", ")}</span> },
              { id: "tags", header: "Tags", value: (r) => r.category_tags.join(", ") },
              { id: "status", header: "Status", value: (r) => r.status, cell: (r) => <StatusBadge status={r.status} /> },
            ]}
          />
        )}
      </QueryState>
    </>
  );
}
