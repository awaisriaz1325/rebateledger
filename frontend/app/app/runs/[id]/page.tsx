"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { DataTable } from "@/components/data-table";
import { ExplainDrawer } from "@/components/explain-drawer";
import { Button, Card, Field, Notice, PageHeader, Select } from "@/components/ui/core";
import { DateText, Money, StatusBadge } from "@/components/ui/finance";
import { EmptyState, QueryState, TableSkeleton } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useJob } from "@/lib/jobs";
import { useNames } from "@/lib/queries";
import { scopeText } from "@/lib/runs";
import { can, useSession } from "@/lib/session";
import type { PeriodResult, Run } from "@/lib/types";

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const query = useQuery({ queryKey: ["run", id], queryFn: async () => unwrap(await api.GET("/api/v1/runs/{run_id}", { params: { path: { run_id: id } } })) });
  return <QueryState query={query}>{(run) => <RunView run={run} />}</QueryState>;
}

function RunView({ run }: { run: Run }) {
  const session = useSession();
  const qc = useQueryClient();
  const names = useNames();
  const active = run.status === "queued" || run.status === "running";
  const job = useJob(active ? run.job_id : null, () => {
    void qc.invalidateQueries({ queryKey: ["run", run.id] });
    void qc.invalidateQueries({ queryKey: ["runs"] });
  });
  const cancel = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/runs/{run_id}/cancel", { params: { path: { run_id: run.id } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["run", run.id] }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const tol = (run.snapshot.tolerance ?? {}) as { abs?: string; pct?: string };
  return (
    <>
      <PageHeader
        title={`Run #${run.number}`}
        description={<>{scopeText(run.scope, names.data)} · <DateText value={run.period_start} /> – <DateText value={run.period_end} /> · engine {run.engine_version}</>}
        actions={active && can(session, "run_reconciliation") ? <Button variant="secondary" onClick={() => cancel.mutate()} loading={cancel.isPending}>Cancel run</Button> : null}
      >
        <div className="mt-2"><StatusBadge status={run.status} /></div>
      </PageHeader>
      {active ? (
        <Card title="Calculating">
          <p className="text-sm" aria-live="polite">{job.data ? `${job.data.progress.toLocaleString("en-US")}${job.data.total ? ` of ${job.data.total.toLocaleString("en-US")}` : ""} steps done…` : "Waiting for a worker…"}</p>
          <p className="mt-1 text-xs text-muted">Results appear only when the whole run finishes. You can leave this page.</p>
        </Card>
      ) : null}
      {run.status === "failed" ? <Notice tone="negative" title="This run failed">{run.error || "The run stopped before finishing. No results were saved."}</Notice> : null}
      {run.status === "succeeded" ? (
        <div className="flex flex-col gap-6">
          <Card>
            <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-5">
              <div><dt className="text-xs text-muted">Total expected</dt><dd className="text-lg font-semibold"><Money value={String(run.totals.expected ?? "0")} /></dd></div>
              <div><dt className="text-xs text-muted">Period results</dt><dd className="num text-left text-lg font-semibold">{Number(run.totals.results ?? 0).toLocaleString("en-US")}</dd></div>
              <div><dt className="text-xs text-muted">Needs review</dt><dd className="num text-left text-lg font-semibold">{Number(run.totals.needs_review ?? 0).toLocaleString("en-US")}</dd></div>
              <div><dt className="text-xs text-muted">Tolerance</dt><dd>${tol.abs ?? "—"} or {tol.pct ?? "—"}%</dd></div>
              <div><dt className="text-xs text-muted">Finished</dt><dd>{formatDateTime(run.finished_at)}</dd></div>
            </dl>
          </Card>
          <Results runId={run.id} />
          <Diff run={run} />
        </div>
      ) : null}
    </>
  );
}

function Results({ runId }: { runId: string }) {
  const names = useNames();
  const [explain, setExplain] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["run-results", runId],
    queryFn: async () => {
      const out: PeriodResult[] = [];
      let cursor: string | undefined;
      do {
        const page = unwrap(await api.GET("/api/v1/runs/{run_id}/results", { params: { path: { run_id: runId }, query: { cursor, limit: 200 } } }));
        out.push(...page.items);
        cursor = page.next_cursor ?? undefined;
      } while (cursor);
      return out;
    },
  });
  return (
    <section aria-labelledby="results-h">
      <h2 id="results-h" className="mb-3 text-base font-semibold">Results in this run</h2>
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No results">No active agreement periods fell in this run&rsquo;s date range.</EmptyState>}>
        {(rows) => (
          <DataTable
            label="Run results"
            rows={rows}
            rowKey={(r) => r.id}
            exportName="run-results"
            onRowClick={(r) => setExplain(r.id)}
            columns={[
              { id: "agreement", header: "Agreement", value: (r) => names.data?.agreement.get(r.agreement_id) ?? "", cell: (r) => <Link href={`/app/agreements/${r.agreement_id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>{names.data?.agreement.get(r.agreement_id) ?? "…"}</Link> },
              { id: "supplier", header: "Supplier", value: (r) => names.data?.supplier.get(r.supplier_id) ?? "" },
              { id: "period", header: "Period", value: (r) => r.period_label },
              { id: "version", header: "Version", value: (r) => r.version_no, align: "right", cell: (r) => `v${r.version_no}` },
              { id: "spend", header: "Eligible spend", value: (r) => r.spend, numeric: true, align: "right", cell: (r) => <Money value={r.spend} /> },
              { id: "tier", header: "Tier", value: (r) => r.tier_reached ?? "", align: "right" },
              { id: "expected", header: "Expected", value: (r) => r.expected ?? "", numeric: true, align: "right", cell: (r) => (r.expected == null ? <StatusBadge status="NEEDS_REVIEW" /> : <Money value={r.expected} emphasize />) },
              { id: "statuses", header: "Flags", value: (r) => r.statuses.join(" "), cell: (r) => <span className="flex flex-wrap gap-1">{r.statuses.filter((s) => s !== "OK").map((s) => <StatusBadge key={s} status={s} />)}</span> },
              { id: "explain", header: "", value: () => "", cell: (r) => <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); setExplain(r.id); }}>Explain</Button> },
            ]}
          />
        )}
      </QueryState>
      <ExplainDrawer resultId={explain} open={explain !== null} onOpenChange={(o) => !o && setExplain(null)} />
    </section>
  );
}

function Diff({ run }: { run: Run }) {
  const names = useNames();
  const runs = useQuery({ queryKey: ["runs", "for-diff"], queryFn: async () => unwrap(await api.GET("/api/v1/runs", { params: { query: { limit: 100 } } })).items });
  const others = (runs.data ?? []).filter((r) => r.id !== run.id && r.status === "succeeded");
  const [other, setOther] = useState<string>("");
  const otherId = other || others.find((r) => r.number < run.number)?.id || "";
  const diff = useQuery({
    queryKey: ["run-diff", otherId, run.id],
    enabled: !!otherId,
    queryFn: async () => unwrap(await api.GET("/api/v1/runs/{run_id}/diff/{other_run_id}", { params: { path: { run_id: otherId, other_run_id: run.id } } })),
  });
  return (
    <Card title="What changed since another run">
      {others.length === 0 ? <p className="text-sm text-muted">There is no other finished run to compare with.</p> : (
        <>
          <Field id="diff-other" label="Compare with" className="max-w-xs">
            <Select id="diff-other" value={otherId} onChange={(e) => setOther(e.target.value)}>
              {others.map((r) => <option key={r.id} value={r.id}>Run #{r.number} ({r.period_start} – {r.period_end})</option>)}
            </Select>
          </Field>
          {diff.isPending ? <TableSkeleton rows={3} /> : diff.isError ? <Notice tone="negative">{errorMessage(diff.error)}</Notice> : (
            <div className="mt-4 text-sm">
              <ul className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-muted">
                <li>{diff.data.batches_added.length} import(s) added, {diff.data.batches_removed.length} removed</li>
                <li>{diff.data.versions_added.length} agreement version(s) added, {diff.data.versions_removed.length} removed</li>
                {diff.data.tolerance_changed ? <li>Tolerance changed</li> : null}
                {diff.data.engine_version_changed ? <li>Engine version changed</li> : null}
              </ul>
              {diff.data.results_changed.length === 0 ? <p>No results changed.</p> : (
                <table className="w-full" aria-label="Changed results">
                  <thead><tr className="text-left text-xs text-muted uppercase"><th className="py-1">Agreement</th><th>Period</th><th className="text-right">Run #{diff.data.from_run}</th><th className="text-right">Run #{diff.data.to_run}</th><th>Why</th></tr></thead>
                  <tbody>
                    {diff.data.results_changed.map((c) => (
                      <tr key={`${c.agreement_id}-${c.period_start}`} className="border-t border-rule">
                        <td className="py-1">{names.data?.agreement.get(c.agreement_id) ?? c.agreement_id}</td>
                        <td>{c.period_start} – {c.period_end}</td>
                        <td className="text-right">{c.before == null ? "—" : <Money value={c.before} />}</td>
                        <td className="text-right">{c.after == null ? "—" : <Money value={c.after} />}</td>
                        <td className="text-xs text-muted">{[c.before_version !== c.after_version ? `version v${c.before_version ?? "—"} → v${c.after_version ?? "—"}` : "", c.inputs_changed ? "input data changed" : ""].filter(Boolean).join("; ") || "status changed"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
