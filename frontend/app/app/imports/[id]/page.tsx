"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { ImportMapping } from "@/components/import-mapping";
import { ImportPresets } from "@/components/import-presets";
import { Button, Card, Checkbox, Field, Input, Notice, PageHeader, Select } from "@/components/ui/core";
import { Money, StatusBadge } from "@/components/ui/finance";
import { ConfirmDialog } from "@/components/ui/overlay";
import { ErrorState, QueryState, TableSkeleton } from "@/components/ui/states";
import { api, errorMessage, idempotencyKey, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useJob, jobDone } from "@/lib/jobs";
import { fetchAllSuppliers } from "@/lib/queries";
import { can, useSession } from "@/lib/session";
import type { Batch } from "@/lib/types";
import type { components } from "@/generated/api";

type Config = components["schemas"]["ConfigIn"];

export default function ImportPage() {
  const { id } = useParams<{ id: string }>();
  const query = useQuery({ queryKey: ["import", id], queryFn: async () => unwrap(await api.GET("/api/v1/imports/{batch_id}", { params: { path: { batch_id: id } } })) });
  return <QueryState query={query}>{(b) => <ImportFlow batch={b} />}</QueryState>;
}

function stepOf(b: Batch): number {
  if (b.status === "committed" || b.status === "voided") return 5;
  if (b.status === "committing") return 5;
  if (b.status === "validated" || b.status === "validating") return 4;
  return b.config.confirmed ? 3 : 2;
}

function ImportFlow({ batch }: { batch: Batch }) {
  const session = useSession();
  const manage = can(session, "manage_imports");
  const step = stepOf(batch);
  return (
    <>
      <PageHeader title={batch.filename} description={<span className="capitalize">{batch.import_type} import · {batch.file_format.toUpperCase()} · uploaded {formatDateTime(batch.created_at)}</span>}>
        <div className="mt-2"><StatusBadge status={batch.status} /></div>
      </PageHeader>
      <ol className="mb-6 flex flex-wrap gap-2 text-xs" aria-label="Import steps">
        {["Upload", "Map columns", "Formats & preview", "Validate", "Commit"].map((label, i) => (
          <li key={label} aria-current={i + 1 === step ? "step" : undefined} className={`rounded-full px-3 py-1 ${i + 1 < step ? "bg-positive-soft text-positive" : i + 1 === step ? "bg-brand text-on-brand" : "bg-surface-2 text-muted"}`}>{i + 1}. {label}</li>
        ))}
      </ol>
      {batch.status === "committed" || batch.status === "voided" ? <Result batch={batch} manage={manage} /> : !manage ? <Notice tone="info">This import is in progress. Someone with import rights can finish it.</Notice> : batch.status === "committing" ? <Progress batch={batch} /> : <Configure batch={batch} />}
    </>
  );
}

function Configure({ batch }: { batch: Batch }) {
  const qc = useQueryClient();
  const preview = useQuery({ queryKey: ["import-preview", batch.id, batch.config.encoding, batch.config.delimiter, batch.config.sheet, batch.config.header_row], queryFn: async () => unwrap(await api.GET("/api/v1/imports/{batch_id}/preview", { params: { path: { batch_id: batch.id } } })) });
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["import", batch.id] }), qc.invalidateQueries({ queryKey: ["import-preview", batch.id] }), qc.invalidateQueries({ queryKey: ["validate-preview", batch.id] })]);
  const save = useMutation({
    mutationFn: async (body: Config) => unwrap(await api.PUT("/api/v1/imports/{batch_id}/config", { params: { path: { batch_id: batch.id } }, body })),
    onSuccess: () => refresh(),
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="flex flex-col gap-6">
      <FileSettings batch={batch} onSave={(c) => save.mutate(c)} />
      {preview.isPending ? <TableSkeleton /> : preview.isError ? <ErrorState error={preview.error} onRetry={() => void preview.refetch()} /> : (
        <>
          <ImportPresets batch={batch} preview={preview.data} onApplied={() => void refresh()} />
          {/* Remount when the saved mapping changes (e.g. a preset was applied) so the form shows it. */}
          <ImportMapping key={JSON.stringify(batch.config.columns ?? {})} batch={batch} preview={preview.data} saving={save.isPending} onSave={(c) => save.mutate(c)} />
        </>
      )}
      {batch.config.confirmed ? <ValidatePreview batch={batch} /> : null}
    </div>
  );
}

function FileSettings({ batch, onSave }: { batch: Batch; onSave: (c: Config) => void }) {
  const c = batch.config as Record<string, unknown>;
  return (
    <Card title="File">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        {batch.file_format === "csv" ? (
          <>
            <Field id="enc" label="Text encoding" hint="Detected automatically; change it if characters look wrong.">
              <Select id="enc" value={String(c.encoding ?? "utf-8")} onChange={(e) => onSave({ encoding: e.target.value as Config["encoding"] })}>
                <option value="utf-8">UTF-8</option><option value="utf-8-sig">UTF-8 with BOM</option><option value="utf-16">UTF-16</option><option value="cp1252">Windows-1252</option>
              </Select>
            </Field>
            <Field id="delim" label="Delimiter">
              <Select id="delim" value={String(c.delimiter ?? ",")} onChange={(e) => onSave({ delimiter: e.target.value as Config["delimiter"] })}>
                <option value=",">Comma</option><option value=";">Semicolon</option><option value={"\t"}>Tab</option><option value="|">Pipe</option>
              </Select>
            </Field>
          </>
        ) : (
          <Field id="sheet" label="Worksheet">
            <Select id="sheet" value={String(c.sheet ?? "")} onChange={(e) => onSave({ sheet: e.target.value })}>
              {((c.sheets as string[] | undefined) ?? []).map((s) => <option key={s} value={s}>{s}</option>)}
            </Select>
          </Field>
        )}
        <Field id="header-row" label="Header is on row">
          <Input id="header-row" inputMode="numeric" defaultValue={String(c.header_row ?? 1)} onBlur={(e) => { const n = Number.parseInt(e.target.value, 10); if (n >= 1 && n <= 100 && n !== c.header_row) onSave({ header_row: n }); }} />
        </Field>
      </div>
    </Card>
  );
}

function ValidatePreview({ batch }: { batch: Batch }) {
  const qc = useQueryClient();
  const preview = useQuery({ queryKey: ["validate-preview", batch.id], queryFn: async () => unwrap(await api.POST("/api/v1/imports/{batch_id}/validate-preview", { params: { path: { batch_id: batch.id } } })) });
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId, (status) => {
    setJobId(null);
    if (status !== "succeeded") toast.error("Validation did not finish. Try again.");
    void qc.invalidateQueries({ queryKey: ["import", batch.id] });
  });
  const validate = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/imports/{batch_id}/validate", { params: { path: { batch_id: batch.id } } })),
    onSuccess: (r) => setJobId(r.job_id),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const rows = preview.data?.rows ?? [];
  const bad = rows.filter((r) => !r.ok).length;
  return (
    <Card title="Preview (first 200 rows)">
      {preview.isPending ? <TableSkeleton /> : preview.isError ? <ErrorState error={preview.error} /> : preview.data.config_problems.length ? (
        <Notice tone="warning" title="Finish the mapping"><ul className="list-disc pl-4">{preview.data.config_problems.map((p) => <li key={p}>{p}</li>)}</ul></Notice>
      ) : (
        <>
          <p className="mb-3 text-sm">{rows.length - bad} of {rows.length} preview rows are valid{bad ? `; ${bad} have errors` : ""}.</p>
          {bad ? (
            <ul className="mb-4 max-h-64 overflow-y-auto rounded-md border border-rule text-sm">
              {rows.filter((r) => !r.ok || r.issues.length).slice(0, 50).map((r) => (
                <li key={r.row} className="border-b border-rule px-3 py-2 last:border-0">
                  <strong>Row {r.row}</strong>: {r.issues.map((i) => `${i.column ? `${i.column}: ` : ""}${i.message}${i.value ? ` (“${i.value}”)` : ""}`).join("; ")}
                </li>
              ))}
            </ul>
          ) : null}
          <Button onClick={() => validate.mutate()} loading={validate.isPending || (!!jobId && !jobDone(job.data?.status))}>Validate the whole file</Button>
          {jobId && job.data ? <p className="mt-2 text-xs text-muted" aria-live="polite">Checked {job.data.progress.toLocaleString("en-US")} rows…</p> : null}
        </>
      )}
      {batch.status === "validated" ? <Validated batch={batch} /> : null}
    </Card>
  );
}

function Validated({ batch }: { batch: Batch }) {
  const qc = useQueryClient();
  const stats = batch.stats as Record<string, unknown>;
  const unknown = (stats.unknown_supplier_codes as { code: string; rows: number }[] | undefined) ?? [];
  const errorsCount = Number(stats.rows_error ?? 0);
  const [mode, setMode] = useState<"all_or_nothing" | "skip_invalid">("all_or_nothing");
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId, (status) => {
    setJobId(null);
    if (status !== "succeeded") toast.error("The commit did not finish. Nothing was saved.");
    void qc.invalidateQueries({ queryKey: ["import", batch.id] });
  });
  const commit = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/imports/{batch_id}/commit", { params: { path: { batch_id: batch.id } }, body: { mode }, headers: { "Idempotency-Key": idempotencyKey() } })),
    onSuccess: (r) => setJobId(r.job_id),
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="mt-6 border-t border-rule pt-4">
      <h3 className="text-sm font-semibold">Full validation</h3>
      <dl className="mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-muted">Rows read</dt><dd className="num text-left">{Number(stats.rows_read ?? 0).toLocaleString("en-US")}</dd></div>
        <div><dt className="text-xs text-muted">Valid</dt><dd className="num text-left">{Number(stats.rows_valid ?? 0).toLocaleString("en-US")}</dd></div>
        <div><dt className="text-xs text-muted">With errors</dt><dd className={`num text-left ${errorsCount ? "text-negative" : ""}`}>{errorsCount.toLocaleString("en-US")}</dd></div>
        <div><dt className="text-xs text-muted">Warnings</dt><dd className="num text-left">{Number(stats.warnings ?? 0).toLocaleString("en-US")}</dd></div>
      </dl>
      {stats.failure ? <div className="mt-3"><Notice tone="negative">{String(stats.failure)}</Notice></div> : null}
      {errorsCount || Number(stats.warnings ?? 0) ? <a className="mt-3 inline-block text-sm text-brand underline" href={`/api/v1/imports/${batch.id}/errors.csv`}>Download the error report (CSV)</a> : null}
      {unknown.length ? <UnknownSuppliers batchId={batch.id} codes={unknown} /> : null}
      <fieldset className="mt-4 flex flex-col gap-2">
        <legend className="text-sm font-medium">How to commit</legend>
        <label className="flex items-center gap-2 text-sm"><input type="radio" name="mode" checked={mode === "all_or_nothing"} onChange={() => setMode("all_or_nothing")} /> All or nothing (recommended) — import only if every row is valid</label>
        <label className="flex items-center gap-2 text-sm"><input type="radio" name="mode" checked={mode === "skip_invalid"} onChange={() => setMode("skip_invalid")} /> Import the valid rows and skip the invalid ones (they stay listed in the report)</label>
      </fieldset>
      <Button className="mt-4" onClick={() => commit.mutate()} loading={commit.isPending || !!jobId} disabled={mode === "all_or_nothing" && errorsCount > 0}>Commit import</Button>
      {jobId && job.data ? <p className="mt-2 text-xs text-muted" aria-live="polite">Committing… {job.data.progress.toLocaleString("en-US")} rows processed</p> : null}
    </div>
  );
}

function UnknownSuppliers({ batchId, codes }: { batchId: string; codes: { code: string; rows: number }[] }) {
  const qc = useQueryClient();
  const suppliers = useQuery({ queryKey: ["suppliers", "all"], queryFn: fetchAllSuppliers });
  const [choices, setChoices] = useState<Record<string, string>>({});
  const resolve = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/imports/{batch_id}/resolve-suppliers", {
      params: { path: { batch_id: batchId } },
      body: { codes: Object.fromEntries(codes.map(({ code }) => { const c = choices[code] ?? "create"; return [code, c === "create" ? { action: "create" as const, name: code } : { action: "map" as const, supplier_id: c }]; })) },
    })),
    onSuccess: async () => { toast.success("Supplier codes resolved — validate again"); await qc.invalidateQueries({ queryKey: ["import", batchId] }); await qc.invalidateQueries({ queryKey: ["suppliers"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="mt-4">
      <Notice tone="warning" title={`${codes.length} supplier code(s) are not known`}>Create a supplier for each, or map the code to an existing supplier.</Notice>
      <ul className="mt-3 flex flex-col gap-2">
        {codes.map(({ code, rows }) => (
          <li key={code} className="grid grid-cols-1 items-center gap-2 sm:grid-cols-[200px_1fr]">
            <span className="font-mono text-sm">{code} <span className="text-xs text-muted">({rows} rows)</span></span>
            <label className="sr-only" htmlFor={`code-${code}`}>Action for {code}</label>
            <Select id={`code-${code}`} value={choices[code] ?? "create"} onChange={(e) => setChoices({ ...choices, [code]: e.target.value })}>
              <option value="create">Create a new supplier “{code}”</option>
              {(suppliers.data ?? []).map((s) => <option key={s.id} value={s.id}>Map to {s.name}</option>)}
            </Select>
          </li>
        ))}
      </ul>
      <Button className="mt-3" variant="secondary" onClick={() => resolve.mutate()} loading={resolve.isPending}>Apply</Button>
    </div>
  );
}

function Progress({ batch }: { batch: Batch }) {
  const qc = useQueryClient();
  const job = useJob(batch.job_id, () => void qc.invalidateQueries({ queryKey: ["import", batch.id] }));
  return (
    <Card title="Committing">
      <p className="text-sm" aria-live="polite">{job.data ? `${job.data.progress.toLocaleString("en-US")} rows processed${job.data.total ? ` of ${job.data.total.toLocaleString("en-US")}` : ""}…` : "Starting…"}</p>
      <p className="mt-2 text-xs text-muted">Nothing becomes visible until the whole batch is saved. You can leave this page.</p>
    </Card>
  );
}

function Result({ batch, manage }: { batch: Batch; manage: boolean }) {
  const qc = useQueryClient();
  const stats = batch.stats as Record<string, unknown>;
  const totals = (stats.totals_by_supplier as Record<string, string> | undefined) ?? {};
  const suppliers = useQuery({ queryKey: ["suppliers", "all"], queryFn: fetchAllSuppliers });
  const names = new Map((suppliers.data ?? []).map((s) => [s.id, s.name]));
  const [voiding, setVoiding] = useState(false);
  const [reason, setReason] = useState("");
  const [tplName, setTplName] = useState("");
  const [tplDefault, setTplDefault] = useState(true);
  const voidBatch = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/imports/{batch_id}/void", { params: { path: { batch_id: batch.id } }, body: { reason } })),
    onSuccess: () => { setVoiding(false); toast.success("Import voided; affected results are marked stale"); void qc.invalidateQueries(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const saveTemplate = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/import-templates", { body: { name: tplName, import_type: batch.import_type as components["schemas"]["TemplateIn"]["import_type"], batch_id: batch.id, is_default: tplDefault } })),
    onSuccess: () => { setTplName(""); toast.success("Template saved"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="flex flex-col gap-6">
      {batch.status === "voided" ? <Notice tone="warning" title="Voided">Voided {batch.voided_at ? formatDateTime(batch.voided_at) : ""}: {batch.void_reason}. Its rows are excluded from new runs; past runs are unchanged.</Notice> : null}
      <Card title="Result">
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          {[["Rows read", stats.rows_read], ["Committed", stats.rows_committed], ["Skipped (invalid)", stats.rows_skipped], ["Duplicates skipped", stats.duplicates], ["Warnings", stats.warnings]].map(([k, v]) => (
            <div key={String(k)}><dt className="text-xs text-muted">{String(k)}</dt><dd className="num text-left text-lg font-semibold">{Number(v ?? 0).toLocaleString("en-US")}</dd></div>
          ))}
        </dl>
        <p className="mt-3 text-sm text-muted">Data from {String(stats.date_from ?? "—")} to {String(stats.date_to ?? "—")}.</p>
        {Object.keys(totals).length ? (
          <table className="mt-4 w-full max-w-lg text-sm" aria-label="Totals by supplier">
            <thead><tr className="text-left text-xs text-muted uppercase"><th>Supplier</th><th className="text-right">Total</th></tr></thead>
            <tbody>{Object.entries(totals).map(([sid, amount]) => <tr key={sid} className="border-t border-rule"><td className="py-1"><Link href={`/app/suppliers/${sid}`} className="hover:underline">{names.get(sid) ?? sid}</Link></td><td className="text-right"><Money value={amount} /></td></tr>)}</tbody>
          </table>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-3 text-sm">
          <a className="text-brand underline" href={`/api/v1/imports/${batch.id}/errors.csv`}>Download row report (CSV)</a>
          <Link className="text-brand underline" href="/app/runs">Start a run →</Link>
        </div>
      </Card>
      {manage && batch.status === "committed" ? (
        <Card title="Save these settings as a template">
          <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); if (tplName.trim()) saveTemplate.mutate(); }}>
            <Field id="tpl-name" label="Template name"><Input id="tpl-name" value={tplName} onChange={(e) => setTplName(e.target.value)} maxLength={120} /></Field>
            <Checkbox id="tpl-default" label="Use by default for this import type" checked={tplDefault} onChange={(e) => setTplDefault(e.target.checked)} />
            <Button type="submit" variant="secondary" loading={saveTemplate.isPending}>Save template</Button>
          </form>
        </Card>
      ) : null}
      {manage && batch.status === "committed" ? (
        <Card title="Void this import">
          <p className="mb-3 text-sm text-muted">Voiding excludes these rows from future runs. Runs that used them are marked stale, never altered.</p>
          <Field id="void-reason" label="Reason"><Input id="void-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></Field>
          <Button className="mt-3" variant="danger" disabled={reason.trim().length < 3} onClick={() => setVoiding(true)}>Void import</Button>
          <ConfirmDialog open={voiding} onOpenChange={setVoiding} title="Void this import?" description="Rows are kept for history but excluded from all new calculations." confirmLabel="Void" typeToConfirm={batch.filename} pending={voidBatch.isPending} onConfirm={() => voidBatch.mutate()} />
        </Card>
      ) : null}
    </div>
  );
}
