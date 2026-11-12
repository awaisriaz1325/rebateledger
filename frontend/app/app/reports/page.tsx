"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { DataTable, type Column } from "@/components/data-table";
import { Button, Card, Field, Input, Notice, PageHeader, Select } from "@/components/ui/core";
import { DateText, Money, StatusBadge, statusLabel } from "@/components/ui/finance";
import { EmptyState, QueryState } from "@/components/ui/states";
import { toast } from "sonner";
import { api, errorMessage, idempotencyKey, unwrap } from "@/lib/api";
import { downloadExport, useExporter } from "@/lib/exports";
import { formatDateTime } from "@/lib/format";
import { useNames } from "@/lib/queries";
import { can, useSession } from "@/lib/session";
import type { ReportInfo, ReportPreview } from "@/lib/types";
import type { components } from "@/generated/api";

type ReportKey = components["schemas"]["ExportIn"]["report"];
type Format = components["schemas"]["ExportIn"]["format"];
type Row = Record<string, string>;

const RECON_STATUSES = ["MATCHED", "NOT_EARNED", "PENDING", "SHORT_PAID", "MISSING", "OVERPAID", "NEEDS_REVIEW"];

export default function ReportsPage() {
  const catalogue = useQuery({ queryKey: ["reports"], queryFn: async () => unwrap(await api.GET("/api/v1/reports")) });
  const [key, setKey] = useState<ReportKey>("reconciliation_summary");
  return (
    <>
      <PageHeader title="Reports" description="Preview any report on screen, then export it as CSV, Excel or PDF. Exports are prepared in the background and downloaded through a link that expires in 15 minutes." />
      <QueryState query={catalogue}>
        {(reports) => {
          const current = reports.find((r) => r.key === key) ?? reports[0];
          return (
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-[260px_1fr]">
              <nav aria-label="Reports">
                <ul className="flex flex-col gap-1">
                  {reports.map((r) => (
                    <li key={r.key}>
                      <button type="button" aria-current={r.key === current?.key ? "page" : undefined} onClick={() => setKey(r.key as ReportKey)} className={`w-full rounded-md px-3 py-2 text-left text-sm ${r.key === current?.key ? "bg-brand-soft font-medium text-brand" : "hover:bg-surface-2"}`}>
                        {r.title}
                        <span className="block text-xs font-normal text-muted">{r.description}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </nav>
              {current ? <ReportView key={current.key} report={current} /> : null}
            </div>
          );
        }}
      </QueryState>
      <RecentExports />
    </>
  );
}

function ReportView({ report }: { report: ReportInfo }) {
  const session = useSession();
  const names = useNames();
  const exporter = useExporter();
  const [supplier, setSupplier] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [status, setStatus] = useState("");
  const has = (f: string) => report.filters.includes(f);
  const params = {
    supplier_id: supplier || undefined,
    period_from: from || undefined,
    period_to: to || undefined,
    status: status || undefined,
  };
  const blocked = report.requires_supplier && !supplier;
  const preview = useQuery({
    queryKey: ["report-preview", report.key, params],
    enabled: !blocked,
    queryFn: async () => unwrap(await api.GET("/api/v1/reports/preview", { params: { query: { report: report.key as ReportKey, ...params } } })),
  });
  const exportAs = (format: Format) =>
    exporter.run(format, async () =>
      unwrap(await api.POST("/api/v1/exports", { body: { report: report.key as ReportKey, format, params }, headers: { "Idempotency-Key": idempotencyKey() } })),
    );
  const canExport = can(session, "export");
  return (
    <section aria-labelledby="report-title" className="min-w-0">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="report-title" className="text-base font-semibold">{report.title}</h2>
            <p className="text-sm text-muted">{report.description}</p>
          </div>
          {canExport ? (
            <div className="flex flex-wrap gap-2" role="group" aria-label="Export">
              {report.formats.map((f) => (
                <Button key={f} size="sm" variant="secondary" disabled={blocked || exporter.busy !== null} loading={exporter.busy === f} onClick={() => void exportAs(f as Format)}>
                  Download {f === "xlsx" ? "Excel" : f.toUpperCase()}
                </Button>
              ))}
            </div>
          ) : null}
        </div>
        <div className="mt-4 flex flex-wrap items-end gap-3">
          {has("supplier_id") ? (
            <Field id="r-supplier" label="Supplier" required={report.requires_supplier}>
              <Select id="r-supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
                <option value="">{report.requires_supplier ? "Choose…" : "All suppliers"}</option>
                {(names.data?.suppliers ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
            </Field>
          ) : null}
          {has("period_from") ? <Field id="r-from" label={report.key === "import_history" || report.key.startsWith("claims") || report.key === "recovery_report" ? "From" : "Periods from"}><Input id="r-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field> : null}
          {has("period_to") ? <Field id="r-to" label={report.key === "import_history" || report.key.startsWith("claims") || report.key === "recovery_report" ? "To" : "Periods to"}><Input id="r-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field> : null}
          {has("status") ? (
            <Field id="r-status" label="Status">
              <Select id="r-status" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">All</option>
                {report.key === "claims_register" ? (
                  <><option value="open">Open</option><option value="closed">Closed</option></>
                ) : RECON_STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s)}</option>)}
              </Select>
            </Field>
          ) : null}
        </div>
      </Card>
      <div className="mt-4">
        {blocked ? <Notice tone="info">Choose a supplier to see their statement.</Notice> : (
          <QueryState query={preview} isEmpty={(p) => p.row_count === 0} empty={<EmptyState title="Nothing to report">No rows match these filters.</EmptyState>}>
            {(p) => <PreviewTable preview={p} />}
          </QueryState>
        )}
      </div>
    </section>
  );
}

function cellFor(kind: string, value: string | undefined) {
  if (value === undefined || value === "") return <span className="text-muted">—</span>;
  if (kind === "money") return <Money value={value} />;
  if (kind === "date") return <DateText value={value} />;
  if (kind === "datetime") return formatDateTime(value);
  return value;
}

function PreviewTable({ preview }: { preview: ReportPreview }) {
  const columns: Column<Row>[] = preview.columns.map((c) => ({
    id: c.key,
    header: c.label,
    value: (r) => r[c.key] ?? "",
    numeric: c.kind === "money" || c.kind === "number" || c.kind === "int",
    align: c.kind === "money" || c.kind === "number" || c.kind === "int" ? "right" : "left",
    cell: c.key === "status" ? (r) => (r.status ? <StatusBadge status={r.status} /> : null) : (r) => cellFor(c.kind, r[c.key]),
  }));
  const totals = Object.entries(preview.totals);
  return (
    <>
      {preview.truncated ? <div className="mb-3"><Notice tone="info">Showing the first 1,000 of {preview.row_count.toLocaleString("en-US")} rows. Exports include every row.</Notice></div> : null}
      <DataTable label={preview.title} rows={preview.rows.map((r, i) => ({ ...r, __row: String(i) }))} rowKey={(r) => r.__row ?? ""} columns={columns} />
      {totals.length ? (
        <dl className="mt-3 flex flex-wrap justify-end gap-6 text-sm" aria-label="Totals">
          {totals.map(([k, v]) => (
            <div key={k} className="text-right">
              <dt className="text-xs text-muted">Total {preview.columns.find((c) => c.key === k)?.label.toLowerCase() ?? k}</dt>
              <dd className="font-semibold"><Money value={v} /></dd>
            </div>
          ))}
        </dl>
      ) : null}
    </>
  );
}

function RecentExports() {
  const session = useSession();
  const query = useQuery({
    queryKey: ["exports"],
    enabled: can(session, "export"),
    queryFn: async () => unwrap(await api.GET("/api/v1/exports")),
    refetchInterval: (q) => (q.state.data?.some((e) => e.status === "queued" || e.status === "running") ? 2000 : false),
  });
  const [busy, setBusy] = useState<string | null>(null);
  if (!can(session, "export")) return null;
  return (
    <section id="exports" aria-labelledby="exports-h" className="mt-10">
      <h2 id="exports-h" className="mb-3 text-base font-semibold">Recent exports</h2>
      <QueryState query={query} isEmpty={(e) => e.length === 0} empty={<p className="text-sm text-muted">Nothing exported yet.</p>}>
        {(rows) => (
          <ul className="divide-y divide-rule rounded-lg border border-rule bg-surface">
            {rows.map((e) => (
              <li key={e.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
                <div className="min-w-0">
                  <p className="truncate font-medium">{e.filename || `${e.report.replace(/_/g, " ")} (${e.format.toUpperCase()})`}</p>
                  <p className="text-xs text-muted">
                    Requested {formatDateTime(e.created_at)}
                    {e.row_count != null ? ` · ${e.row_count.toLocaleString("en-US")} rows` : ""}
                    {e.expires_at && e.status === "succeeded" ? ` · available until ${formatDateTime(e.expires_at)}` : ""}
                    {e.error ? ` · ${e.error}` : ""}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <StatusBadge status={e.status} />
                  {e.status === "succeeded" ? (
                    <Button size="sm" variant="secondary" loading={busy === e.id} onClick={async () => { setBusy(e.id); try { await downloadExport(e.id); } catch (err) { toast.error(errorMessage(err)); } finally { setBusy(null); } }}>Download</Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </section>
  );
}
