"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { DataTable } from "@/components/data-table";
import { Button, Card, Field, Input, PageHeader, Select } from "@/components/ui/core";
import { DateText, Money, StatusBadge } from "@/components/ui/finance";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, idempotencyKey, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useNames } from "@/lib/queries";
import { scopeText } from "@/lib/runs";
import { can, useSession } from "@/lib/session";
import type { Run } from "@/lib/types";

export default function RunsPage() {
  const session = useSession();
  const query = useInfiniteQuery({
    queryKey: ["runs"],
    initialPageParam: undefined as number | undefined,
    queryFn: async ({ pageParam }) => unwrap(await api.GET("/api/v1/runs", { params: { query: { cursor: pageParam, limit: 50 } } })),
    getNextPageParam: (last) => (last.next_cursor ? Number(last.next_cursor) : undefined),
    refetchInterval: (q) => (q.state.data?.pages[0]?.items.some((r) => r.status === "queued" || r.status === "running") ? 2000 : false),
  });
  const flat = { ...query, data: query.data?.pages.flatMap((p) => p.items) };
  return (
    <>
      <PageHeader title="Runs" description="Each run calculates expected rebates from a frozen snapshot of agreements and data. Runs are never edited; re-run to update." />
      {can(session, "run_reconciliation") ? <StartRun /> : null}
      <div className="mt-6">
        <QueryState query={flat} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No runs yet">Start a run once you have an active agreement and imported purchases.</EmptyState>}>
          {(rows) => <RunsTable rows={rows} />}
        </QueryState>
        {query.hasNextPage ? <Button variant="secondary" className="mt-3" onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage}>Load older runs</Button> : null}
      </div>
    </>
  );
}

function RunsTable({ rows }: { rows: Run[] }) {
  const router = useRouter();
  const names = useNames();
  return (
    <DataTable
      label="Runs"
      rows={rows}
      rowKey={(r) => r.id}
      exportName="runs"
      onRowClick={(r) => router.push(`/app/runs/${r.id}`)}
      columns={[
        { id: "number", header: "Run", value: (r) => r.number, align: "right", cell: (r) => <Link href={`/app/runs/${r.id}`} className="font-medium hover:underline">#{r.number}</Link> },
        { id: "status", header: "Status", value: (r) => r.status, cell: (r) => <StatusBadge status={r.status} /> },
        { id: "scope", header: "Scope", value: (r) => scopeText(r.scope, names.data) },
        { id: "period", header: "Period", value: (r) => `${r.period_start} – ${r.period_end}`, cell: (r) => <span><DateText value={r.period_start} /> – <DateText value={r.period_end} /></span> },
        { id: "expected", header: "Expected", value: (r) => String(r.totals.expected ?? ""), numeric: true, align: "right", cell: (r) => (r.totals.expected ? <Money value={String(r.totals.expected)} /> : <span className="text-muted">—</span>) },
        { id: "review", header: "Needs review", value: (r) => Number(r.totals.needs_review ?? 0), align: "right" },
        { id: "created", header: "Started", value: (r) => r.created_at, cell: (r) => formatDateTime(r.created_at) },
        { id: "engine", header: "Engine", value: (r) => r.engine_version, hidden: true },
      ]}
    />
  );
}

function StartRun() {
  const router = useRouter();
  const qc = useQueryClient();
  const names = useNames();
  const year = new Date().getFullYear();
  const [scope, setScope] = useState<"all" | "supplier" | "agreements">("all");
  const [supplierId, setSupplierId] = useState("");
  const [agreementIds, setAgreementIds] = useState<string[]>([]);
  const [start, setStart] = useState(`${year}-01-01`);
  const [end, setEnd] = useState(`${year}-12-31`);
  const start_ = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/runs", {
          body: {
            period_start: start,
            period_end: end,
            scope: scope === "supplier" ? { type: "supplier", supplier_id: supplierId } : scope === "agreements" ? { type: "agreements", agreement_ids: agreementIds } : { type: "all" },
          },
          headers: { "Idempotency-Key": idempotencyKey() },
        }),
      ),
    onSuccess: async (run) => {
      await qc.invalidateQueries({ queryKey: ["runs"] });
      router.push(`/app/runs/${run.id}`);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const invalid = !start || !end || end < start || (scope === "supplier" && !supplierId) || (scope === "agreements" && agreementIds.length === 0);
  return (
    <Card title="Start a run">
      <form className="grid grid-cols-1 items-end gap-4 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); if (!invalid) start_.mutate(); }}>
        <Field id="run-scope" label="Scope">
          <Select id="run-scope" value={scope} onChange={(e) => setScope(e.target.value as typeof scope)}>
            <option value="all">All active agreements</option>
            <option value="supplier">One supplier</option>
            <option value="agreements">Chosen agreements</option>
          </Select>
        </Field>
        {scope === "supplier" ? (
          <Field id="run-supplier" label="Supplier">
            <Select id="run-supplier" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Choose…</option>
              {(names.data?.suppliers ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
        ) : null}
        {scope === "agreements" ? (
          <Field id="run-agreements" label="Agreements" hint="Hold Ctrl or ⌘ to choose several.">
            <Select id="run-agreements" multiple className="h-24" value={agreementIds} onChange={(e) => setAgreementIds([...e.target.selectedOptions].map((o) => o.value))}>
              {(names.data?.agreements ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </Select>
          </Field>
        ) : null}
        <Field id="run-start" label="From"><Input id="run-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
        <Field id="run-end" label="To" error={end && start && end < start ? "Must be on or after the start date." : undefined}><Input id="run-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
        <div className="sm:col-span-4"><Button type="submit" loading={start_.isPending} disabled={invalid}>Start run</Button></div>
      </form>
    </Card>
  );
}
