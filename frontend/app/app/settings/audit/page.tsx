"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Card, Field, Input } from "@/components/ui/core";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export default function AuditPage() {
  const [filters, setFilters] = useState({ actor: "", action: "", date_from: "", date_to: "" });
  const [applied, setApplied] = useState(filters);
  const query = useInfiniteQuery({
    queryKey: ["audit", applied],
    initialPageParam: undefined as number | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(await api.GET("/api/v1/org/audit-events", {
        params: { query: { actor: applied.actor || undefined, action: applied.action || undefined, date_from: applied.date_from || undefined, date_to: applied.date_to || undefined, cursor: pageParam, limit: 50 } },
      })),
    getNextPageParam: (last) => (last.next_cursor ? Number(last.next_cursor) : undefined),
  });
  const qs = new URLSearchParams(Object.entries(applied).filter(([, v]) => v)).toString();
  const rows = query.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Card title="Audit log" actions={<a href={`/api/v1/org/audit-events/export.csv${qs ? `?${qs}` : ""}`} className="text-sm font-medium text-brand hover:underline">Export CSV</a>}>
      <form className="mb-4 grid grid-cols-1 items-end gap-3 sm:grid-cols-5" onSubmit={(e) => { e.preventDefault(); setApplied(filters); }}>
        <Field id="f-actor" label="Actor"><Input id="f-actor" value={filters.actor} onChange={(e) => setFilters({ ...filters, actor: e.target.value })} /></Field>
        <Field id="f-action" label="Action starts with"><Input id="f-action" placeholder="e.g. claim." value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })} /></Field>
        <Field id="f-from" label="From"><Input id="f-from" type="date" value={filters.date_from} onChange={(e) => setFilters({ ...filters, date_from: e.target.value })} /></Field>
        <Field id="f-to" label="To"><Input id="f-to" type="date" value={filters.date_to} onChange={(e) => setFilters({ ...filters, date_to: e.target.value })} /></Field>
        <Button type="submit" variant="secondary">Apply</Button>
      </form>
      {query.isPending ? <TableSkeleton /> : query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : rows.length === 0 ? <EmptyState title="No events match" /> : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="Audit events">
              <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th className="py-2">#</th><th>When</th><th>Actor</th><th>Action</th><th>Object</th></tr></thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id} className="border-b border-rule last:border-0 align-top">
                    <td className="num py-2 pr-3 text-left text-muted">{e.seq}</td>
                    <td className="pr-3 whitespace-nowrap">{formatDateTime(e.occurred_at)}</td>
                    <td className="pr-3">{e.actor_label}<span className="block text-xs text-muted">{e.actor_type}</span></td>
                    <td className="pr-3 font-mono text-xs">{e.action}</td>
                    <td className="font-mono text-xs text-muted">{e.object_type} {e.object_id.slice(0, 8)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {query.hasNextPage ? <Button variant="secondary" className="mt-4" loading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>Load more</Button> : null}
          <p className="mt-3 text-xs text-muted">Each event is hash-chained to the previous one; the chain is verified daily.</p>
        </>
      )}
    </Card>
  );
}
