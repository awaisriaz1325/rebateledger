"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Card, Field, Input, Notice, PageHeader, Select } from "@/components/ui/core";
import { DateText, Money, StatusBadge } from "@/components/ui/finance";
import { QueryState } from "@/components/ui/states";
import { api, errorMessage, idempotencyKey, unwrap } from "@/lib/api";
import { useExporter } from "@/lib/exports";
import { jobDone, useJob } from "@/lib/jobs";
import { useNames } from "@/lib/queries";
import { can, useSession } from "@/lib/session";
import type { AuditCoverage, AuditResult } from "@/lib/types";

/** Look-back recovery audit (v1.2 Phase 20): coverage → calculation → shortfalls → claims. */
export default function RecoveryAuditPage() {
  const session = useSession();
  const names = useNames();
  const year = new Date().getFullYear();
  const [from, setFrom] = useState(`${year - 2}-01-01`);
  const [to, setTo] = useState(`${year - 1}-12-31`);
  const [supplier, setSupplier] = useState("");
  const [checked, setChecked] = useState<{ from: string; to: string; supplier: string } | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [ran, setRan] = useState(false);
  const range = checked ? { period_from: checked.from, period_to: checked.to, supplier_id: checked.supplier || undefined } : null;

  const coverage = useQuery({
    queryKey: ["audit-coverage", range],
    enabled: !!range,
    queryFn: async () => unwrap(await api.GET("/api/v1/recovery-audit/coverage", { params: { query: range! } })),
  });
  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/runs", {
          body: { period_start: checked!.from, period_end: checked!.to, scope: checked!.supplier ? { type: "supplier", supplier_id: checked!.supplier } : { type: "all" } },
          headers: { "Idempotency-Key": idempotencyKey() },
        }),
      ),
    onSuccess: (run) => setJobId(run.job_id ?? null),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const job = useJob(jobId, (status) => {
    if (status === "succeeded") setRan(true);
    else toast.error("The calculation did not finish. Open Runs for details.");
  });
  const running = start.isPending || (!!jobId && !jobDone(job.data?.status));
  const invalid = !from || !to || to < from;

  return (
    <>
      <PageHeader title="Recovery audit" description="Look back up to three years: which supplier rebates were calculated as owed but never received. Included free in pilots. Amounts are identified, not recovered, until the supplier pays." />
      <div className="flex flex-col gap-6">
        <Card title="1. Choose what to audit">
          <form className="grid grid-cols-1 items-end gap-4 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); if (!invalid) { setChecked({ from, to, supplier }); setRan(false); setJobId(null); } }}>
            <Field id="audit-from" label="From"><Input id="audit-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field id="audit-to" label="To" hint="At most three years."><Input id="audit-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
            <Field id="audit-supplier" label="Supplier">
              <Select id="audit-supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
                <option value="">All suppliers</option>
                {(names.data?.suppliers ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
            </Field>
            <Button type="submit" disabled={invalid}>Check coverage</Button>
          </form>
        </Card>

        {range ? (
          <Card title="2. Check coverage">
            <QueryState query={coverage}>
              {(rows) => <Coverage rows={rows} />}
            </QueryState>
            {can(session, "run_reconciliation") ? (
              <div className="mt-4 flex flex-wrap items-center gap-4">
                <Button onClick={() => start.mutate()} loading={running} disabled={running || !coverage.data}>Run the calculation for this range</Button>
                <span className="text-sm text-muted" aria-live="polite">{running ? "Calculating… this can take a minute for three years." : ran ? "Calculation finished." : "Uses your agreements and imported purchases and credits as they are now."}</span>
              </div>
            ) : <Notice tone="info">An Owner, Admin or Analyst runs the calculation.</Notice>}
          </Card>
        ) : null}

        {range && ran ? <Results range={range} /> : null}
      </div>
    </>
  );
}

function Coverage({ rows }: { rows: AuditCoverage[] }) {
  if (rows.length === 0) return <Notice tone="warning">No supplier in this selection has an agreement. Add agreements first.</Notice>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Agreement and purchase-history coverage per supplier</caption>
        <thead><tr className="border-b border-rule text-xs text-muted"><th scope="col" className="py-2 pr-4">Supplier</th><th scope="col" className="pr-4">Agreements</th><th scope="col" className="pr-4">Not covered by an agreement</th><th scope="col">Purchase history</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.supplier_id} className="border-b border-rule align-top last:border-0">
              <td className="py-2 pr-4 font-medium">{r.name}</td>
              <td className="num pr-4">{r.agreements}</td>
              <td className="pr-4">{r.gaps.length ? r.gaps.map((g) => <div key={g.start}><DateText value={g.start} /> – <DateText value={g.end} /></div>) : <span className="text-muted">Fully covered</span>}</td>
              <td>{r.data_from ? <>From <DateText value={r.data_from} /></> : "None imported"}{r.history_starts_late ? <p className="text-xs text-warning">Starts after the audit start: earlier periods will look like nothing was bought.</p> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">Gaps are not guessed: periods without an agreement or without purchases simply produce no shortfall.</p>
    </div>
  );
}

function Results({ range }: { range: { period_from: string; period_to: string; supplier_id?: string } }) {
  const session = useSession();
  const exporter = useExporter();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const audit = useQuery({ queryKey: ["audit", range], queryFn: async () => unwrap(await api.GET("/api/v1/recovery-audit", { params: { query: range } })) });
  const claim = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/recovery-audit/claims", { body: { result_ids: [...selected] }, headers: { "Idempotency-Key": idempotencyKey() } })),
    onSuccess: (out) => {
      toast.success(`${out.claim_ids.length} claim${out.claim_ids.length === 1 ? "" : "s"} created`);
      setSelected(new Set());
      void audit.refetch();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const download = (format: "pdf" | "csv") =>
    exporter.run(format, async () => unwrap(await api.POST("/api/v1/exports", { body: { report: "recovery_audit", format, params: range }, headers: { "Idempotency-Key": idempotencyKey() } })));
  return (
    <Card title="3. Shortfalls found">
      <QueryState query={audit}>
        {(data: AuditResult) => {
          const claimable = data.rows.filter((r) => r.shortfall && !r.claim);
          return (
            <>
              <Notice tone="info" title="Identified, not recovered">{data.note}</Notice>
              <p className="mt-4 text-lg">Identified shortfall: <Money value={data.total_shortfall} emphasize /></p>
              {data.rows.length === 0 ? <p className="mt-2 text-sm text-muted">No short-paid or missing periods in this range.</p> : (
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">Short-paid, missing and needs-review periods</caption>
                    <thead><tr className="border-b border-rule text-xs text-muted"><th scope="col" className="py-2 pr-2"><span className="sr-only">Select</span></th><th scope="col" className="pr-4">Supplier</th><th scope="col" className="pr-4">Agreement</th><th scope="col" className="pr-4">Period</th><th scope="col" className="pr-4 text-right">Expected</th><th scope="col" className="pr-4 text-right">Received</th><th scope="col" className="pr-4 text-right">Shortfall</th><th scope="col" className="pr-4">Status</th><th scope="col">Notes</th></tr></thead>
                    <tbody>
                      {data.rows.map((r) => {
                        const can_ = !!r.shortfall && !r.claim;
                        return (
                          <tr key={r.result_id} className="border-b border-rule align-top last:border-0">
                            <td className="py-2 pr-2">{can_ ? <input type="checkbox" aria-label={`Select ${r.agreement} ${r.period}`} checked={selected.has(r.result_id)} onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(r.result_id); else n.delete(r.result_id); return n; })} /> : null}</td>
                            <td className="pr-4">{r.supplier}</td>
                            <td className="pr-4">{r.agreement}</td>
                            <td className="pr-4">{r.period || <><DateText value={r.period_start} /> – <DateText value={r.period_end} /></>}</td>
                            <td className="pr-4 text-right"><Money value={r.expected} /></td>
                            <td className="pr-4 text-right"><Money value={r.received} /></td>
                            <td className="pr-4 text-right"><Money value={r.shortfall} emphasize /></td>
                            <td className="pr-4"><StatusBadge status={r.status} /><span className="block text-xs text-muted">Overdue {r.age}</span></td>
                            <td className="text-xs">{r.claim ? <span>Open claim {r.claim}</span> : null}{r.deadline ? <p className="text-warning">{r.deadline}</p> : null}{r.status === "NEEDS_REVIEW" ? <p className="text-muted">Not counted: our calculation needs review.</p> : null}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-3">
                {can(session, "edit_claims") && claimable.length ? (
                  <>
                    <Button variant="secondary" onClick={() => setSelected(new Set(claimable.map((r) => r.result_id)))}>Select all claimable ({claimable.length})</Button>
                    <Button disabled={selected.size === 0} loading={claim.isPending} onClick={() => claim.mutate()}>Create claims for {selected.size} period{selected.size === 1 ? "" : "s"}</Button>
                  </>
                ) : null}
                {can(session, "export") ? (
                  <>
                    <Button variant="secondary" loading={exporter.busy === "pdf"} disabled={exporter.busy !== null} onClick={() => void download("pdf")}>Download PDF</Button>
                    <Button variant="secondary" loading={exporter.busy === "csv"} disabled={exporter.busy !== null} onClick={() => void download("csv")}>Download CSV</Button>
                  </>
                ) : null}
                <Link href="/app/claims" className="text-sm text-brand underline">Go to claims</Link>
              </div>
              <p className="mt-2 text-xs text-muted">One claim is created per supplier, each with its normal evidence pack.</p>
            </>
          );
        }}
      </QueryState>
    </Card>
  );
}
