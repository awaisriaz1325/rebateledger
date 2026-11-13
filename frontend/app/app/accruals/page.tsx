"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Card, Checkbox, Field, Input, Notice, PageHeader, Select } from "@/components/ui/core";
import { Money } from "@/components/ui/finance";
import { EmptyState, PermissionDenied, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { downloadCsv } from "@/lib/csv";
import { formatDate, formatDateTime } from "@/lib/format";
import { can, useSession } from "@/lib/session";
import type { components } from "@/generated/api";

type Journal = components["schemas"]["AccrualJournalOut"];
type Excluded = components["schemas"]["AccrualExcludedOut"];

/** Last day of the previous month, as YYYY-MM-DD (local calendar). */
function lastMonthEnd(today = new Date()): string {
  const d = new Date(today.getFullYear(), today.getMonth(), 0);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Month-end accrual journal (v1.1 Phase 15): preview, sign off, download. Never posts to a ledger. */
export default function AccrualsPage() {
  const session = useSession();
  const [closing, setClosing] = useState(lastMonthEnd);
  const journal = useQuery({
    queryKey: ["accruals", closing],
    enabled: /^\d{4}-\d{2}-\d{2}$/.test(closing),
    queryFn: async () => unwrap(await api.GET("/api/v1/accruals/journal", { params: { query: { closing_date: closing } } })),
    retry: false,
  });
  if (!can(session, "export")) return <PermissionDenied />;
  return (
    <>
      <PageHeader title="Month-end accruals" description="The rebate receivable still outstanding at a month end, as a reversing journal you import into your own ledger." />
      <Card className="mb-6">
        <Field id="closing" label="Closing date (last day of a month)">
          <Input id="closing" type="date" className="max-w-xs" value={closing} onChange={(e) => setClosing(e.target.value)} />
        </Field>
      </Card>
      <QueryState query={journal}>{(j) => <JournalView j={j} canSignOff={can(session, "approve")} />}</QueryState>
      <History />
    </>
  );
}

function JournalView({ j, canSignOff }: { j: Journal; canSignOff: boolean }) {
  return (
    <div className="mb-6 flex flex-col gap-6">
      <Notice tone="info" title="How to book this journal">
        Each line debits rebate receivable and credits your offset account for what is still owed on {formatDate(j.closing_date)}; every line reverses on {formatDate(j.reversal_date)}. For the balance to stay right, book supplier credits to the offset account when they arrive, not to the receivable account. Open periods are estimates to date. Have your accountant confirm this treatment.
      </Notice>
      {!j.accounts_configured ? (
        <Notice tone="warning" title="GL accounts not set">Add your account codes under <Link className="underline" href="/app/settings/accounting">Settings → Accounting</Link> before exporting.</Notice>
      ) : null}
      <Card title={<>Outstanding at {formatDate(j.closing_date)}: <Money value={j.total} /></>}>
        {j.lines.length === 0 ? (
          <EmptyState title="Nothing outstanding">No agreement period has an outstanding rebate at this date.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="Accrual lines">
              <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th scope="col" className="py-2">Supplier</th><th scope="col">Agreement</th><th scope="col">Period</th><th scope="col">Basis</th><th scope="col" className="num">Earned</th><th scope="col" className="num">Received</th><th scope="col" className="num">Outstanding</th></tr></thead>
              <tbody>
                {j.lines.map((l) => (
                  <tr key={`${l.agreement_id}-${l.period_start}`} className="border-b border-rule last:border-0">
                    <td className="py-2">{l.supplier_name}</td>
                    <td>{l.agreement_name}</td>
                    <td>{l.period_label || `${formatDate(l.period_start)} – ${formatDate(l.period_end)}`}</td>
                    <td>{l.basis === "open_estimate" ? "Estimate to date" : "Calculated"}</td>
                    <td className="num"><Money value={l.earned} /></td>
                    <td className="num"><Money value={l.received} /></td>
                    <td className="num font-medium"><Money value={l.outstanding} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <LeftOut title="Left out: needs attention" rows={j.excluded} />
      <LeftOut title="Closed periods not calculated yet" rows={j.not_calculated} hint="Run a calculation covering these periods, then reload." />
      {j.last_export ? (
        <Card title="Since the last export for this date">
          <p className="mb-2 text-sm text-muted">Exported {formatDateTime(j.last_export.created_at)}: <Money value={j.last_export.total} /> in {j.last_export.line_count} lines.</p>
          {j.changes_since_last_export.length === 0 ? <p className="text-sm">No changes.</p> : (
            <table className="w-full text-sm" aria-label="Changes since the last export">
              <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th scope="col" className="py-2">Agreement</th><th scope="col">Period start</th><th scope="col" className="num">Before</th><th scope="col" className="num">Now</th></tr></thead>
              <tbody>{j.changes_since_last_export.map((c) => <tr key={`${c.agreement}-${c.period_start}`} className="border-b border-rule last:border-0"><td className="py-2">{c.supplier} — {c.agreement}</td><td>{formatDate(c.period_start)}</td><td className="num">{c.before ? <Money value={c.before} /> : "—"}</td><td className="num">{c.after ? <Money value={c.after} /> : "—"}</td></tr>)}</tbody>
            </table>
          )}
        </Card>
      ) : null}
      {canSignOff ? <SignOff j={j} /> : <Notice tone="info">An Owner or Admin signs off and downloads the journal.</Notice>}
    </div>
  );
}

function LeftOut({ title, rows, hint }: { title: string; rows: Excluded[]; hint?: string }) {
  if (rows.length === 0) return null;
  return (
    <Card title={title}>
      {hint ? <p className="mb-2 text-sm text-muted">{hint}</p> : null}
      <ul className="divide-y divide-rule text-sm">
        {rows.map((x) => <li key={`${x.agreement_name}-${x.period_start}`} className="py-2">{x.supplier_name} — {x.agreement_name}, {formatDate(x.period_start)} – {formatDate(x.period_end)}: {x.reason}</li>)}
      </ul>
    </Card>
  );
}

function SignOff({ j }: { j: Journal }) {
  const qc = useQueryClient();
  const [format, setFormat] = useState<"generic" | "qbo">("generic");
  const [reviewed, setReviewed] = useState(false);
  const exportJournal = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/accruals/journal/export", { body: { closing_date: j.closing_date, format, reviewed: true }, parseAs: "text" })) as unknown as string,
    onSuccess: (csv) => {
      downloadCsv(`rebate-accrual-${j.closing_date.slice(0, 7)}-${format}.csv`, csv);
      toast.success("Journal downloaded and recorded");
      setReviewed(false);
      void qc.invalidateQueries({ queryKey: ["accruals"] });
      void qc.invalidateQueries({ queryKey: ["accrual-exports"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Sign off and download">
      <div className="flex flex-wrap items-end gap-4">
        <Field id="acc-format" label="File format">
          <Select id="acc-format" value={format} onChange={(e) => setFormat(e.target.value as "generic" | "qbo")}>
            <option value="generic">Generic CSV</option>
            <option value="qbo">QuickBooks Online journal import (unverified columns)</option>
          </Select>
        </Field>
        <Checkbox id="acc-reviewed" label="I reviewed the lines, estimates and anything left out" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
        <Button disabled={!reviewed || !j.accounts_configured || j.lines.length === 0} loading={exportJournal.isPending} onClick={() => exportJournal.mutate()}>Download journal</Button>
      </div>
      <p className="mt-2 text-xs text-muted">Each download is recorded with your name, the time and a fingerprint of the file.</p>
    </Card>
  );
}

function History() {
  const query = useQuery({ queryKey: ["accrual-exports"], queryFn: async () => unwrap(await api.GET("/api/v1/accruals/exports")) });
  return (
    <Card title="Export history">
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No exports yet">Signed-off journals appear here.</EmptyState>}>
        {(rows) => (
          <table className="w-full text-sm" aria-label="Accrual export history">
            <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th scope="col" className="py-2">Closing date</th><th scope="col">Exported</th><th scope="col">Format</th><th scope="col" className="num">Lines</th><th scope="col" className="num">Total</th><th scope="col">File fingerprint</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.id} className="border-b border-rule last:border-0"><td className="py-2">{formatDate(r.closing_date)}</td><td>{formatDateTime(r.created_at)}</td><td>{r.format === "qbo" ? "QuickBooks Online" : "Generic CSV"}</td><td className="num">{r.line_count}</td><td className="num"><Money value={r.total} /></td><td className="font-mono text-xs">{r.file_hash.slice(0, 12)}…</td></tr>)}</tbody>
          </table>
        )}
      </QueryState>
    </Card>
  );
}
