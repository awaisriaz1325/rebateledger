"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { DataTable } from "@/components/data-table";
import { Button, Field, PageHeader, Select } from "@/components/ui/core";
import { DateText, Money } from "@/components/ui/finance";
import { Dialog } from "@/components/ui/overlay";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { fetchAllAgreements } from "@/lib/queries";
import { can, useSession } from "@/lib/session";
import type { StatementRow } from "@/lib/types";

type Status = StatementRow["status"];
const STATUSES: Record<Status, string> = {
  agrees: "Agrees",
  purchases_differ: "Purchases differ",
  rate_or_tier_differs: "Rate or tier differs",
  not_calculated: "Not calculated",
  needs_review: "Needs review",
  unconfirmed: "Confirm agreement",
  unmatched: "No agreement",
};

/** Supplier statement compare (v1.2 Phase 22): their numbers next to ours, line by line. */
export default function StatementsPage() {
  const session = useSession();
  const [status, setStatus] = useState<Status | "">("");
  const [assigning, setAssigning] = useState<StatementRow | null>(null);
  const canAssign = can(session, "run_reconciliation");
  const query = useQuery({
    queryKey: ["statements", status],
    queryFn: async () => unwrap(await api.GET("/api/v1/statements", { params: { query: status ? { status } : {} } })),
  });
  const exportHref = `/api/v1/statements/export${status ? `?status=${status}` : ""}`;
  const actions = (
    <>
      <Link href="/app/imports/new?type=statements" className="text-sm text-brand hover:underline">Import a statement →</Link>
      {can(session, "export") ? <a href={exportHref} download className="text-sm text-brand hover:underline">Download differences (CSV)</a> : null}
    </>
  );
  return (
    <>
      <PageHeader title="Supplier statements" description="What each supplier says you earned, next to what we calculated for the same agreement and period. Difference = ours − theirs: a positive difference means the supplier's statement is short." actions={actions} />
      <div className="mb-4 max-w-xs">
        <Field id="statement-status" label="Show">
          <Select id="statement-status" value={status} onChange={(e) => setStatus(e.target.value as Status | "")}>
            <option value="">All lines</option>
            {(Object.keys(STATUSES) as Status[]).map((s) => <option key={s} value={s}>{STATUSES[s]}</option>)}
          </Select>
        </Field>
      </div>
      <QueryState
        query={query}
        isEmpty={(rows) => rows.length === 0}
        empty={<EmptyState title={status ? "No lines with this status" : "No supplier statements yet"} action={status ? undefined : <Link href="/app/imports/new?type=statements" className="text-sm font-medium text-brand underline">Import a supplier statement</Link>}>Import the statement a supplier sends (CSV or XLSX) to compare it with our calculation.</EmptyState>}
      >
        {(rows) => (
          <DataTable
            rows={rows}
            label="Supplier statement lines"
            rowKey={(r) => r.id}
            exportName="supplier-statements"
            columns={[
              { id: "supplier", header: "Supplier", value: (r) => r.supplier_name },
              { id: "agreement", header: "Agreement", value: (r) => r.agreement_name ?? "" , cell: (r) => r.agreement_name ?? <span className="text-muted">—</span> },
              { id: "statement", header: "Statement", value: (r) => r.statement_reference ?? "" },
              { id: "period", header: "Period", value: (r) => r.period_start, cell: (r) => <><DateText value={r.period_start} /> – <DateText value={r.period_end} /></> },
              { id: "theirs", header: "Their rebate", value: (r) => r.theirs, cell: (r) => <Money value={r.theirs} />, align: "right", numeric: true },
              { id: "ours", header: "Our rebate", value: (r) => r.ours, cell: (r) => <Money value={r.ours} />, align: "right", numeric: true },
              { id: "difference", header: "Difference", value: (r) => r.difference, cell: (r) => <Money value={r.difference} emphasize />, align: "right", numeric: true },
              {
                id: "status",
                header: "Status",
                value: (r) => STATUSES[r.status],
                cell: (r) => (
                  <div>
                    <span className="font-medium">{STATUSES[r.status]}</span>
                    <p className="text-xs text-muted">{r.reason}</p>
                    {r.status === "purchases_differ" ? <p className="text-xs text-muted">Purchases: theirs <Money value={r.their_measure} />, ours <Money value={r.our_measure} /></p> : null}
                    {canAssign && (r.status === "unconfirmed" || r.status === "unmatched") ? (
                      <Button variant="secondary" className="mt-1" onClick={() => setAssigning(r)}>{r.status === "unconfirmed" ? "Confirm agreement" : "Choose agreement"}</Button>
                    ) : null}
                  </div>
                ),
              },
            ]}
          />
        )}
      </QueryState>
      {assigning ? <AssignDialog row={assigning} onClose={() => setAssigning(null)} /> : null}
    </>
  );
}

function AssignDialog({ row, onClose }: { row: StatementRow; onClose: () => void }) {
  const qc = useQueryClient();
  const agreements = useQuery({ queryKey: ["agreements-all"], queryFn: fetchAllAgreements });
  const options = (agreements.data ?? []).filter((a) => a.supplier_id === row.supplier_id && a.status !== "archived");
  const [choice, setChoice] = useState<string>(row.agreement_id ?? "");
  const save = useMutation({
    mutationFn: async () => unwrap(await api.PUT("/api/v1/statements/{line_id}/agreement", { params: { path: { line_id: row.id } }, body: { agreement_id: choice || null } })),
    onSuccess: () => {
      toast.success(choice ? "Agreement assigned" : "Agreement cleared");
      void qc.invalidateQueries({ queryKey: ["statements"] });
      onClose();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Agreement for this statement line"
      description={`${row.supplier_name}, ${row.period_start} to ${row.period_end}${row.statement_reference ? `, statement ${row.statement_reference}` : ""}.`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button></>}
    >
      <Field id="statement-agreement" label="Agreement" hint="Only this supplier's agreements are listed. Choose “No agreement” to clear it.">
        <Select id="statement-agreement" value={choice} onChange={(e) => setChoice(e.target.value)}>
          <option value="">No agreement</option>
          {options.map((a) => <option key={a.id} value={a.id}>{a.name}{a.external_reference ? ` (${a.external_reference})` : ""}</option>)}
        </Select>
      </Field>
    </Dialog>
  );
}
