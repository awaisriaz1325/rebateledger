"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { DataTable } from "@/components/data-table";
import { Button, Field, PageHeader, Select } from "@/components/ui/core";
import { DateText, Money, StatusBadge, statusLabel } from "@/components/ui/finance";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { useNames } from "@/lib/queries";
import type { Claim } from "@/lib/types";

const STATUSES = ["draft", "ready", "submitted", "acknowledged", "resolved_partial", "resolved_recovered", "rejected", "written_off"];

export default function ClaimsPage() {
  const router = useRouter();
  const names = useNames();
  const members = useQuery({ queryKey: ["members"], queryFn: async () => unwrap(await api.GET("/api/v1/org/members")) });
  const people = new Map((members.data ?? []).map((m) => [m.user_id, m.name]));
  const [state, setState] = useState("open");
  const [supplier, setSupplier] = useState("");
  const [assignee, setAssignee] = useState("");
  const query = useInfiniteQuery({
    queryKey: ["claims", state, supplier, assignee],
    initialPageParam: undefined as number | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/claims", {
          params: {
            query: {
              open: state === "open" ? true : state === "closed" ? false : undefined,
              status: STATUSES.includes(state) ? state : undefined,
              supplier_id: supplier || undefined,
              assignee_id: assignee || undefined,
              cursor: pageParam,
              limit: 100,
            },
          },
        }),
      ),
    getNextPageParam: (last) => (last.next_cursor ? Number(last.next_cursor) : undefined),
  });
  const flat = { ...query, data: query.data?.pages.flatMap((p) => p.items) };
  return (
    <>
      <PageHeader title="Claims" description="Recovery work for missing and short-paid rebates. Claims open from the Discrepancies page." actions={<Link href="/app/discrepancies" className="inline-flex h-9 items-center rounded-md bg-brand px-4 text-sm font-medium text-on-brand">Find discrepancies</Link>} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field id="c-state" label="Status">
          <Select id="c-state" value={state} onChange={(e) => setState(e.target.value)}>
            <option value="open">Open</option><option value="closed">Closed</option><option value="all">All</option>
            {STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
          </Select>
        </Field>
        <Field id="c-supplier" label="Supplier">
          <Select id="c-supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
            <option value="">All</option>
            {(names.data?.suppliers ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <Field id="c-assignee" label="Assignee">
          <Select id="c-assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            <option value="">Anyone</option>
            {(members.data ?? []).map((m) => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
          </Select>
        </Field>
      </div>
      <QueryState query={flat} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No claims here">Open a claim from a short-paid or missing period on the Discrepancies page.</EmptyState>}>
        {(rows: Claim[]) => (
          <DataTable
            label="Claims"
            rows={rows}
            rowKey={(r) => r.id}
            exportName="claims"
            onRowClick={(r) => router.push(`/app/claims/${r.id}`)}
            columns={[
              { id: "number", header: "Claim", value: (r) => r.number, align: "right", cell: (r) => <Link href={`/app/claims/${r.id}`} className="font-medium hover:underline">#{r.number}</Link> },
              { id: "title", header: "Title", value: (r) => r.title },
              { id: "supplier", header: "Supplier", value: (r) => names.data?.supplier.get(r.supplier_id) ?? "" },
              { id: "status", header: "Status", value: (r) => r.status, cell: (r) => <span className="flex gap-1"><StatusBadge status={r.status} />{r.pending_write_off ? <StatusBadge status="pending" /> : null}</span> },
              { id: "claimed", header: "Claimed", value: (r) => r.claimed_amount, numeric: true, align: "right", cell: (r) => <Money value={r.claimed_amount} /> },
              { id: "recovered", header: "Recovered", value: (r) => r.recovered_amount, numeric: true, align: "right", cell: (r) => <Money value={r.recovered_amount} /> },
              { id: "assignee", header: "Assignee", value: (r) => (r.assignee_id ? people.get(r.assignee_id) ?? "" : "") },
              { id: "due", header: "Due", value: (r) => r.due_date ?? "", cell: (r) => <DateText value={r.due_date} /> },
              { id: "follow", header: "Follow up", value: (r) => r.follow_up_date ?? "", cell: (r) => <DateText value={r.follow_up_date} /> },
              { id: "identified", header: "Identified", value: (r) => r.identified_amount, numeric: true, align: "right", hidden: true, cell: (r) => <Money value={r.identified_amount} /> },
            ]}
          />
        )}
      </QueryState>
      {query.hasNextPage ? <Button variant="secondary" className="mt-3" onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage}>Load more</Button> : null}
    </>
  );
}
