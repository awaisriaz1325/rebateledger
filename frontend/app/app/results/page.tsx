"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Field, PageHeader, Select } from "@/components/ui/core";
import { ReconTable, RECON_STATUSES } from "@/components/recon-table";
import { statusLabel } from "@/components/ui/finance";
import { EmptyState, QueryState, StaleBanner } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { useNames } from "@/lib/queries";
import { can, useSession } from "@/lib/session";

export default function ResultsPage() {
  const session = useSession();
  const names = useNames();
  const [supplier, setSupplier] = useState("");
  const [status, setStatus] = useState("");
  const [stale, setStale] = useState("");
  const query = useQuery({
    queryKey: ["reconciliation", supplier, status, stale],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/reconciliation", { params: { query: { supplier_id: supplier || undefined, status: status || undefined, stale: stale === "" ? undefined : stale === "yes" } } })),
  });
  const staleRows = (query.data ?? []).filter((r) => r.stale);
  const runLink = can(session, "run_reconciliation") ? <Link href="/app/runs" className="font-medium text-brand underline">Start a run</Link> : null;
  return (
    <>
      <PageHeader title="Results" description="Expected rebate per agreement period from the latest run, against credits received. Click a row to see exactly how it was calculated." />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field id="f-supplier" label="Supplier">
          <Select id="f-supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
            <option value="">All suppliers</option>
            {(names.data?.suppliers ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <Field id="f-status" label="Status">
          <Select id="f-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {RECON_STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
          </Select>
        </Field>
        <Field id="f-stale" label="Freshness">
          <Select id="f-stale" value={stale} onChange={(e) => setStale(e.target.value)}>
            <option value="">All</option><option value="yes">Stale only</option><option value="no">Current only</option>
          </Select>
        </Field>
      </div>
      {staleRows.length ? <div className="mb-4"><StaleBanner reason={`${staleRows.length} result(s) affected; ${staleRows[0]?.stale_reason ?? "inputs changed"}`} action={runLink} /></div> : null}
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No results to show" action={runLink}>{supplier || status || stale ? "Nothing matches these filters." : "Run a calculation to see expected rebates."}</EmptyState>}>
        {(rows) => <ReconTable rows={rows} label="Reconciliation results" exportName="results" />}
      </QueryState>
    </>
  );
}
