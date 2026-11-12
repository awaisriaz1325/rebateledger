"use client";

import { useState } from "react";
import { Button, Card, Field, Input, Notice, Select } from "@/components/ui/core";
import type { Batch, ImportPreview } from "@/lib/types";
import type { components } from "@/generated/api";

type Config = components["schemas"]["ConfigIn"];
export const DATE_FORMATS = ["YYYY-MM-DD", "MM/DD/YYYY", "DD/MM/YYYY", "M/D/YY", "D/M/YY", "DD.MM.YYYY", "YYYYMMDD", "DD-MMM-YYYY", "MM-DD-YYYY"] as const;

/** Import wizard step 2–3: map columns, flags and explicit formats. Dates are never guessed. */
export function ImportMapping({ batch, preview, saving, onSave }: { batch: Batch; preview: ImportPreview; saving: boolean; onSave: (c: Config) => void }) {
  const cfg = batch.config as Record<string, unknown>;
  const existing = (cfg.columns as Record<string, string> | undefined) ?? {};
  const [columns, setColumns] = useState<Record<string, string>>(() => (Object.keys(existing).length ? existing : preview.suggested_columns));
  const [flags, setFlags] = useState<[string, string][]>(() => Object.entries((cfg.flags as Record<string, string> | undefined) ?? {}));
  const [fmt, setFmt] = useState({
    date_format: (cfg.date_format as string | undefined) ?? "",
    decimal_separator: (cfg.decimal_separator as string | undefined) ?? ".",
    thousands_separator: (cfg.thousands_separator as string | undefined) ?? ",",
    negative_style: (cfg.negative_style as string | undefined) ?? "minus",
    credit_sign: (cfg.credit_sign as string | undefined) ?? "positive",
  });
  const dateCandidates = [...new Set(Object.values(preview.date_format_candidates).flat())];
  const ambiguous = Object.values(preview.date_format_candidates).some((c) => c.length > 1);
  const hasDates = preview.fields.some((f) => f.kind === "date" && columns[f.name]);
  const missingRequired = preview.fields.filter((f) => f.required && !columns[f.name]);
  function submit() {
    const body: Config = {
      columns: Object.fromEntries(Object.entries(columns).filter(([, v]) => v)),
      flags: Object.fromEntries(flags.filter(([k, v]) => k && v)),
      decimal_separator: fmt.decimal_separator as Config["decimal_separator"],
      thousands_separator: fmt.thousands_separator as Config["thousands_separator"],
      negative_style: fmt.negative_style as Config["negative_style"],
    };
    if (fmt.date_format) body.date_format = fmt.date_format as Config["date_format"];
    if (batch.import_type === "credits") body.credit_sign = fmt.credit_sign as Config["credit_sign"];
    onSave(body);
  }
  return (
    <>
      <Card title="Map columns">
        <p className="mb-4 text-sm text-muted">We suggested matches from your header names. Check each one.</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {preview.fields.map((f) => (
            <Field key={f.name} id={`map-${f.name}`} label={f.label} required={f.required}>
              <Select id={`map-${f.name}`} value={columns[f.name] ?? ""} onChange={(e) => setColumns({ ...columns, [f.name]: e.target.value })}>
                <option value="">— not in this file —</option>
                {preview.header.filter(Boolean).map((h) => <option key={h} value={h}>{h}</option>)}
              </Select>
            </Field>
          ))}
        </div>
        {preview.supports_flags ? (
          <div className="mt-5">
            <p className="text-sm font-medium">Line flags (Y/N columns such as special pricing, drop ship, promo)</p>
            {flags.map(([name, header], i) => (
              <div key={i} className="mt-2 grid grid-cols-[1fr_1fr_auto] items-end gap-2">
                <Field id={`flag-${i}`} label="Flag name"><Input id={`flag-${i}`} value={name} onChange={(e) => setFlags(flags.map((x, j) => (j === i ? [e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"), x[1]] : x)))} /></Field>
                <Field id={`flagcol-${i}`} label="Column">
                  <Select id={`flagcol-${i}`} value={header} onChange={(e) => setFlags(flags.map((x, j) => (j === i ? [x[0], e.target.value] : x)))}>
                    <option value="">Choose…</option>{preview.header.filter(Boolean).map((h) => <option key={h} value={h}>{h}</option>)}
                  </Select>
                </Field>
                <Button variant="ghost" size="sm" onClick={() => setFlags(flags.filter((_, j) => j !== i))}>Remove</Button>
              </div>
            ))}
            <Button variant="secondary" size="sm" className="mt-2" onClick={() => setFlags([...flags, ["special_pricing", ""]])}>Add flag column</Button>
          </div>
        ) : null}
      </Card>
      <Card title="Formats">
        {hasDates && ambiguous ? <div className="mb-4"><Notice tone="warning" title="Dates are ambiguous">Values like 03/04/2026 could be March 4 or April 3. Choose the format your system uses — it is never guessed.</Notice></div> : null}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {hasDates ? (
            <Field id="date-format" label="Date format" required hint={dateCandidates.length ? `Formats that fit your sample: ${dateCandidates.join(", ")}` : "No sample format matched; check the date column."}>
              <Select id="date-format" value={fmt.date_format} onChange={(e) => setFmt({ ...fmt, date_format: e.target.value })}>
                <option value="">Choose…</option>
                {DATE_FORMATS.map((d) => <option key={d} value={d}>{d}{dateCandidates.includes(d) ? " (matches sample)" : ""}</option>)}
              </Select>
            </Field>
          ) : null}
          <Field id="decimal" label="Decimal separator">
            <Select id="decimal" value={fmt.decimal_separator} onChange={(e) => setFmt({ ...fmt, decimal_separator: e.target.value, thousands_separator: e.target.value === "," ? "." : "," })}>
              <option value=".">Point (1,234.56)</option><option value=",">Comma (1.234,56)</option>
            </Select>
          </Field>
          <Field id="negative" label="Negative amounts look like">
            <Select id="negative" value={fmt.negative_style} onChange={(e) => setFmt({ ...fmt, negative_style: e.target.value })}>
              <option value="minus">-123.45</option><option value="parentheses">(123.45)</option><option value="trailing_minus">123.45-</option>
            </Select>
          </Field>
          {batch.import_type === "credits" ? (
            <Field id="credit-sign" label="Credits in this file are">
              <Select id="credit-sign" value={fmt.credit_sign} onChange={(e) => setFmt({ ...fmt, credit_sign: e.target.value })}>
                <option value="positive">Positive numbers</option><option value="negative">Negative numbers</option>
              </Select>
            </Field>
          ) : null}
        </div>
        {missingRequired.length ? <p className="mt-4 text-sm text-negative">Map the required fields: {missingRequired.map((f) => f.label).join(", ")}.</p> : null}
        <Button className="mt-4" onClick={submit} loading={saving} disabled={missingRequired.length > 0 || (hasDates && !fmt.date_format)}>Save mapping and preview</Button>
      </Card>
      <Card title="Raw sample (first rows)">
        <div className="overflow-x-auto">
          <table className="text-xs" aria-label="Raw file sample">
            <thead><tr>{preview.header.map((h, i) => <th key={i} className="border-b border-rule px-2 py-1 text-left font-semibold whitespace-nowrap">{h || `(column ${i + 1})`}</th>)}</tr></thead>
            <tbody>{preview.sample_rows.slice(0, 10).map((r, i) => <tr key={i}>{preview.header.map((_, j) => <td key={j} className="border-b border-rule px-2 py-1 font-mono whitespace-nowrap">{r[j] ?? ""}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

