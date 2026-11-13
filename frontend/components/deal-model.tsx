"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { DEFAULT_TERMS, TermsEditor } from "@/components/terms-editor";
import { Button, Card, Field, Input, Notice, Select } from "@/components/ui/core";
import { Dialog } from "@/components/ui/overlay";
import { api, errorMessage, unwrap } from "@/lib/api";
import { downloadCsv, toCsv } from "@/lib/csv";
import { formatDate, formatMoney, formatRatePercent } from "@/lib/format";
import { fetchAllSuppliers } from "@/lib/queries";
import type { components } from "@/generated/api";
import type { Terms } from "@/lib/types";

type Result = components["schemas"]["DealModelOut"];
interface Option { key: number; label: string; terms: Terms }

const MAX_OPTIONS = 4;

function lastFullYear(today = new Date()): { start: string; end: string } {
  const y = today.getFullYear() - 1;
  return { start: `${y}-01-01`, end: `${y}-12-31` };
}

/** "+10%" style label for a sensitivity factor ("1.1"). Display only; no arithmetic on money. */
export function factorLabel(factor: string): string {
  const [whole = "0", frac = ""] = factor.split(".");
  const pct = Number(whole) * 100 + Number((frac + "00").slice(0, 2)) - 100;
  return `${pct > 0 ? "+" : ""}${pct}% spend`;
}

/** Deal modelling (v1.1 Phase 13): compare proposed terms on real past purchases. */
export function DealModel() {
  const suppliers = useQuery({ queryKey: ["suppliers", "all"], queryFn: fetchAllSuppliers });
  const [supplierId, setSupplierId] = useState("");
  const [range, setRange] = useState(lastFullYear);
  const [options, setOptions] = useState<Option[]>([{ key: 1, label: "Option A", terms: DEFAULT_TERMS }]);
  const [nextKey, setNextKey] = useState(2);
  const [draftFrom, setDraftFrom] = useState<Option | null>(null);

  const agreements = useQuery({
    queryKey: ["agreements", "for-model", supplierId],
    enabled: !!supplierId,
    queryFn: async () => unwrap(await api.GET("/api/v1/agreements", { params: { query: { supplier_id: supplierId, status: "active", limit: 50 } } })).items,
  });

  const evaluate = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/deal-models/evaluate", {
          body: { supplier_id: supplierId, window_start: range.start, window_end: range.end, options: options.map((o) => ({ label: o.label, terms: o.terms })) },
        }),
      ),
    onError: (e) => toast.error(errorMessage(e)),
  });

  async function copyFromAgreement(agreementId: string) {
    try {
      const a = unwrap(await api.GET("/api/v1/agreements/{agreement_id}", { params: { path: { agreement_id: agreementId } } }));
      const current = a.versions.find((v) => v.status === "active") ?? a.versions[0];
      if (!current || options.length >= MAX_OPTIONS) return;
      setOptions([...options, { key: nextKey, label: `Current: ${a.name}`.slice(0, 60), terms: current.terms }]);
      setNextKey(nextKey + 1);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  const letter = (i: number) => String.fromCharCode(65 + i);
  const update = (key: number, patch: Partial<Option>) => setOptions(options.map((o) => (o.key === key ? { ...o, ...patch } : o)));

  return (
    <div className="flex flex-col gap-6">
      <Card title="What to model">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field id="m-supplier" label="Supplier" required>
            <Select id="m-supplier" value={supplierId} onChange={(e) => { setSupplierId(e.target.value); evaluate.reset(); }}>
              <option value="">Choose…</option>
              {(suppliers.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
          <Field id="m-start" label="History from" hint="Whole periods inside the window are used."><Input id="m-start" type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} /></Field>
          <Field id="m-end" label="History to" hint="At most 24 months."><Input id="m-end" type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} /></Field>
        </div>
        {supplierId && (agreements.data ?? []).length > 0 ? (
          <div className="mt-4 flex flex-wrap items-end gap-2">
            <Field id="m-copy" label="Add the current terms of an agreement as an option">
              <Select id="m-copy" value="" disabled={options.length >= MAX_OPTIONS} onChange={(e) => e.target.value && void copyFromAgreement(e.target.value)}>
                <option value="">Choose an agreement…</option>
                {(agreements.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </Select>
            </Field>
          </div>
        ) : null}
      </Card>

      {options.map((o, i) => (
        <section key={o.key} aria-labelledby={`opt-h-${o.key}`} className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <h2 id={`opt-h-${o.key}`} className="text-lg font-semibold">Option {letter(i)}</h2>
            <div className="flex items-end gap-2">
              <Field id={`opt-label-${o.key}`} label={`Name of option ${letter(i)}`}><Input id={`opt-label-${o.key}`} value={o.label} maxLength={60} onChange={(e) => update(o.key, { label: e.target.value })} /></Field>
              {options.length > 1 ? <Button variant="ghost" onClick={() => setOptions(options.filter((x) => x.key !== o.key))}>Remove option {letter(i)}</Button> : null}
            </div>
          </div>
          <TermsEditor value={o.terms} onChange={(t) => update(o.key, { terms: t })} />
        </section>
      ))}

      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" disabled={options.length >= MAX_OPTIONS} onClick={() => { setOptions([...options, { key: nextKey, label: `Option ${letter(options.length)}`, terms: DEFAULT_TERMS }]); setNextKey(nextKey + 1); }}>Add option</Button>
        <Button loading={evaluate.isPending} disabled={!supplierId || !range.start || !range.end || options.some((o) => !o.label.trim())} onClick={() => evaluate.mutate()}>Compare options</Button>
      </div>
      <p className="text-sm text-muted">Agreement effective dates are ignored here: each option is applied to the history window. They are kept if you turn an option into a draft.</p>

      {evaluate.data ? <Comparison result={evaluate.data} options={options} onDraft={setDraftFrom} /> : null}
      <CreateDraft supplierId={supplierId} option={draftFrom} onClose={() => setDraftFrom(null)} />
    </div>
  );
}

function Comparison({ result, options, onDraft }: { result: Result; options: Option[]; onDraft: (o: Option) => void }) {
  const factors = result.options[0]?.sensitivity.map((s) => s.factor) ?? [];
  function exportCsv() {
    const header = ["Option", "Period", "From", "To", "Expected rebate (estimate)", "Eligible spend", "Tier reached", "Status"];
    const rows = result.options.flatMap((o) => o.periods.map((p) => [o.label, p.label, p.start, p.end, p.expected ?? "", p.spend, p.tier_reached ?? "", p.statuses.join(" ")]));
    downloadCsv(`deal-model-${result.window_start}-${result.window_end}.csv`, toCsv(header, rows));
  }
  return (
    <Card title="Comparison (estimate)" actions={<Button variant="secondary" size="sm" onClick={exportCsv}>Download CSV</Button>}>
      <p className="mb-4 text-sm text-muted">
        What each option would have paid on real purchases from {formatDate(result.window_start)} to {formatDate(result.window_end)}. Estimates: the same engine as real runs, applied to past data.
      </p>
      {result.options.some((o) => !o.complete) ? <div className="mb-4"><Notice tone="warning" title="Some periods need review">An option could not be fully calculated (for example a growth rebate without a baseline). Its total leaves those periods out.</Notice></div> : null}
      <div className="overflow-x-auto">
        <table className="w-full text-sm" aria-label="Option comparison">
          <thead>
            <tr className="border-b border-rule text-left text-xs text-muted uppercase">
              <th scope="col" className="py-2">Measure</th>
              {result.options.map((o) => <th key={o.label} scope="col" className="num">{o.label}</th>)}
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-rule"><th scope="row" className="py-2 text-left font-medium">Total rebate</th>{result.options.map((o) => <td key={o.label} className="num font-semibold">{formatMoney(o.total_expected)}{o.complete ? "" : " *"}</td>)}</tr>
            <tr className="border-b border-rule"><th scope="row" className="py-2 text-left font-medium">Eligible spend</th>{result.options.map((o) => <td key={o.label} className="num">{formatMoney(o.total_spend)}</td>)}</tr>
            <tr className="border-b border-rule"><th scope="row" className="py-2 text-left font-medium">Effective rate</th>{result.options.map((o) => <td key={o.label} className="num">{o.effective_rate ? formatRatePercent(o.effective_rate) : "—"}</td>)}</tr>
            {factors.map((f, i) => (
              <tr key={f} className="border-b border-rule"><th scope="row" className="py-2 text-left font-normal text-muted">If {factorLabel(f)}</th>{result.options.map((o) => <td key={o.label} className="num text-muted">{formatMoney(o.sensitivity[i]?.total_expected)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3 className="mt-6 mb-2 font-semibold">By period</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" aria-label="Rebate by period">
          <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th scope="col" className="py-2">Period</th>{result.options.map((o) => <th key={o.label} scope="col" className="num">{o.label}</th>)}</tr></thead>
          <tbody>
            {(result.options[0]?.periods ?? []).map((_, pi) => (
              <tr key={pi} className="border-b border-rule last:border-0">
                <th scope="row" className="py-2 text-left font-normal">{result.options.map((o) => o.periods[pi]?.label).find(Boolean)}</th>
                {result.options.map((o) => {
                  const p = o.periods[pi];
                  return <td key={o.label} className="num">{p ? (p.expected === null ? "Needs review" : `${formatMoney(p.expected)}${p.tier_reached ? ` (tier ${p.tier_reached})` : ""}`) : "—"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-6 flex flex-wrap gap-2">
        {options.map((o) => <Button key={o.key} variant="secondary" size="sm" onClick={() => onDraft(o)}>Create agreement draft from “{o.label}”</Button>)}
      </div>
    </Card>
  );
}

function CreateDraft({ supplierId, option, onClose }: { supplierId: string; option: Option | null; onClose: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/agreements", { body: { supplier_id: supplierId, name, external_reference: null, notes: `Created from deal model option “${option?.label ?? ""}”.`, terms: option!.terms } })),
    onSuccess: (a) => { void qc.invalidateQueries({ queryKey: ["agreements"] }); toast.success("Draft saved"); onClose(); router.push(`/app/agreements/${a.id}`); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog
      open={option !== null}
      onOpenChange={(o) => { if (!o) { onClose(); setName(""); } }}
      title="Create agreement draft"
      description="The option's terms, including its effective dates, become a new draft. Nothing is activated."
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={create.isPending} disabled={!name.trim()} onClick={() => create.mutate()}>Save draft</Button></>}
    >
      <Field id="draft-name" label="Agreement name" required><Input id="draft-name" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} /></Field>
    </Dialog>
  );
}
