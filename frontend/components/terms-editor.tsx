"use client";

/**
 * Agreement rule builder (SPEC §4.4.5): form-based terms with inline validation and a
 * live plain-English summary computed by the backend (no logic duplicated here).
 * Decimal values are kept as strings end to end.
 */
import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, Card, Checkbox, Field, Input, Notice, Select } from "@/components/ui/core";
import { api, unwrap } from "@/lib/api";
import type { Terms } from "@/lib/types";

type Component = Terms["components"][number];
type Rule = NonNullable<Terms["eligibility"]>[number];
type Tier = NonNullable<Component["tiers"]>[number];

export const DEFAULT_TERMS: Terms = {
  effective_from: new Date().toISOString().slice(0, 4) + "-01-01",
  effective_to: null,
  period_type: "quarterly",
  fiscal_aligned: true,
  custom_periods: [],
  date_basis: "invoice_date",
  measure: "spend",
  spend_basis: "net_of_returns",
  threshold_comparison: "gte",
  negative_result: "floor_at_zero",
  rounding_mode: "half_up",
  payment_terms_days: 60,
  stacking: "stackable",
  prorate_thresholds_on_partial_period: false,
  zero_baseline_policy: "needs_review",
  cap_amount: null,
  minimum_payout: null,
  eligibility: [],
  components: [{ key: "base", type: "flat_percent", rate: "0.02", tiers: [] }],
};

const COMPONENT_TYPES: { value: Component["type"]; label: string }[] = [
  { value: "flat_percent", label: "Flat % of eligible spend" },
  { value: "per_unit", label: "Amount per unit" },
  { value: "tiered_all_units", label: "Tiered — all units (reached tier pays on everything)" },
  { value: "tiered_incremental", label: "Tiered — incremental (each band its own rate)" },
  { value: "growth_incremental", label: "Growth — % of measure above baseline" },
  { value: "growth_threshold", label: "Growth — % of spend if growth target met" },
  { value: "fixed_bonus", label: "Fixed bonus at a threshold" },
];

function useDebouncedValue<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function TermsEditor({ value, onChange }: { value: Terms; onChange: (t: Terms) => void }) {
  const debounced = useDebouncedValue(value, 350);
  const check = useQuery({
    queryKey: ["terms-check", debounced],
    queryFn: async () => unwrap(await api.POST("/api/v1/agreement-terms/check", { body: debounced })),
    retry: false,
  });
  const set = <K extends keyof Terms>(k: K, v: Terms[K]) => onChange({ ...value, [k]: v });
  const opt = (s: string) => (s.trim() === "" ? null : s.trim());

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_380px]">
      <div className="flex flex-col gap-6">
        <Card title="When and how it is measured">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field id="t-from" label="Effective from" required><Input id="t-from" type="date" value={value.effective_from} onChange={(e) => set("effective_from", e.target.value)} /></Field>
            <Field id="t-to" label="Effective to" hint="Leave empty if open-ended."><Input id="t-to" type="date" value={value.effective_to ?? ""} onChange={(e) => set("effective_to", e.target.value || null)} /></Field>
            <Field id="t-period" label="Period">
              <Select id="t-period" value={value.period_type} onChange={(e) => set("period_type", e.target.value as Terms["period_type"])}>
                <option value="monthly">Monthly</option><option value="quarterly">Quarterly</option><option value="semiannual">Half-yearly</option><option value="annual">Annual</option><option value="custom">Custom periods</option>
              </Select>
            </Field>
            <div className="flex items-end pb-2"><Checkbox id="t-fiscal" label="Align periods to our fiscal year" checked={value.fiscal_aligned} onChange={(e) => set("fiscal_aligned", e.target.checked)} /></div>
            <Field id="t-basis" label="Date that decides the period">
              <Select id="t-basis" value={value.date_basis} onChange={(e) => set("date_basis", e.target.value as Terms["date_basis"])}>
                <option value="invoice_date">Invoice date</option><option value="ship_date">Ship date</option><option value="receipt_date">Receipt date</option>
              </Select>
            </Field>
            <Field id="t-measure" label="Tiers are tested against">
              <Select id="t-measure" value={value.measure} onChange={(e) => set("measure", e.target.value as Terms["measure"])}>
                <option value="spend">Eligible spend</option><option value="quantity">Eligible units</option>
              </Select>
            </Field>
            <Field id="t-spend-basis" label="Do returns reduce the measure?">
              <Select id="t-spend-basis" value={value.spend_basis} onChange={(e) => set("spend_basis", e.target.value as Terms["spend_basis"])}>
                <option value="net_of_returns">Yes — net of returns</option><option value="gross">No — gross purchases</option>
              </Select>
            </Field>
            <Field id="t-cmp" label="A threshold is met when the measure is">
              <Select id="t-cmp" value={value.threshold_comparison} onChange={(e) => set("threshold_comparison", e.target.value as Terms["threshold_comparison"])}>
                <option value="gte">At least the threshold (≥)</option><option value="gt">More than the threshold (&gt;)</option>
              </Select>
            </Field>
          </div>
          {value.period_type === "custom" ? <CustomPeriods value={value} onChange={onChange} /> : null}
        </Card>

        <Card title="What it pays" actions={<Button size="sm" variant="secondary" onClick={() => set("components", [...value.components, { key: `c${value.components.length + 1}`, type: "flat_percent", rate: "0.01", tiers: [] }])}><Plus size={14} aria-hidden="true" /> Add component</Button>}>
          <div className="flex flex-col gap-4">
            {value.components.map((c, i) => (
              <ComponentEditor key={i} index={i} value={c} measure={value.measure}
                onChange={(nc) => set("components", value.components.map((x, j) => (j === i ? nc : x)))}
                onRemove={value.components.length > 1 ? () => set("components", value.components.filter((_, j) => j !== i)) : undefined} />
            ))}
          </div>
        </Card>

        <Card title="Which purchases count" actions={<Button size="sm" variant="secondary" onClick={() => set("eligibility", [...(value.eligibility ?? []), { action: "exclude", field: "flag", flag: "special_pricing", values: [] }])}><Plus size={14} aria-hidden="true" /> Add rule</Button>}>
          {(value.eligibility ?? []).length === 0 ? <p className="text-sm text-muted">All purchases from this supplier count. Add rules to include or exclude SKUs, categories, branches or flagged lines. Exclude rules win over include rules.</p> : null}
          <div className="flex flex-col gap-3">
            {(value.eligibility ?? []).map((r, i) => (
              <RuleEditor key={i} index={i} value={r} onChange={(nr) => set("eligibility", (value.eligibility ?? []).map((x, j) => (j === i ? nr : x)))} onRemove={() => set("eligibility", (value.eligibility ?? []).filter((_, j) => j !== i))} />
            ))}
          </div>
        </Card>

        <Card title="Limits, rounding and payment">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field id="t-cap" label="Cap per period (USD)" hint="Optional"><Input id="t-cap" inputMode="decimal" value={value.cap_amount ?? ""} onChange={(e) => set("cap_amount", opt(e.target.value))} /></Field>
            <Field id="t-min" label="Minimum payout (USD)" hint="Below this the period pays nothing. Optional."><Input id="t-min" inputMode="decimal" value={value.minimum_payout ?? ""} onChange={(e) => set("minimum_payout", opt(e.target.value))} /></Field>
            <Field id="t-neg" label="If the result is negative">
              <Select id="t-neg" value={value.negative_result} onChange={(e) => set("negative_result", e.target.value as Terms["negative_result"])}>
                <option value="floor_at_zero">Pay nothing (floor at zero)</option><option value="allow_clawback">Owe it back (clawback)</option>
              </Select>
            </Field>
            <Field id="t-round" label="Rounding (2 decimals, once at the end)">
              <Select id="t-round" value={value.rounding_mode} onChange={(e) => set("rounding_mode", e.target.value as Terms["rounding_mode"])}>
                <option value="half_up">Half up</option><option value="half_even">Half even (banker&rsquo;s)</option>
              </Select>
            </Field>
            <Field id="t-terms" label="Credit expected within (days after period end)"><Input id="t-terms" inputMode="numeric" value={String(value.payment_terms_days)} onChange={(e) => set("payment_terms_days", Number.parseInt(e.target.value || "0", 10) || 0)} /></Field>
            <Field id="t-stack" label="May a purchase also count toward this supplier's other agreements?">
              <Select id="t-stack" value={value.stacking} onChange={(e) => set("stacking", e.target.value as Terms["stacking"])}>
                <option value="stackable">Yes (stackable)</option><option value="exclusive">No (exclusive)</option>
              </Select>
            </Field>
            <Field id="t-zero" label="Growth with a zero baseline">
              <Select id="t-zero" value={value.zero_baseline_policy} onChange={(e) => set("zero_baseline_policy", e.target.value as Terms["zero_baseline_policy"])}>
                <option value="needs_review">Ask me (needs review)</option><option value="qualifies">Counts as growth</option><option value="does_not_qualify">Does not qualify</option>
              </Select>
            </Field>
            <div className="flex items-end pb-2"><Checkbox id="t-prorate" label="Prorate thresholds in partial periods" checked={value.prorate_thresholds_on_partial_period} onChange={(e) => set("prorate_thresholds_on_partial_period", e.target.checked)} /></div>
          </div>
        </Card>
      </div>

      <aside className="xl:sticky xl:top-20 xl:self-start" aria-live="polite">
        <Card title="Summary">
          {check.isPending ? <p className="text-sm text-muted">Checking…</p> : check.data?.valid ? (
            <p className="text-sm leading-relaxed">{check.data.summary}</p>
          ) : (
            <Notice tone="negative" title="These terms are not valid yet">{check.data?.error ?? "Fill in the required fields (decimals like 0.02 for 2%)."}</Notice>
          )}
          {check.data?.warnings.length ? <div className="mt-3"><Notice tone="warning">{check.data.warnings.join(" ")}</Notice></div> : null}
          <p className="mt-4 text-xs text-muted">Rates are fractions: 0.02 means 2%. The summary is generated from the rules, not written by hand.</p>
        </Card>
      </aside>
    </div>
  );
}

export function useTermsValid(value: Terms): boolean | undefined {
  const debounced = useDebouncedValue(value, 350);
  const check = useQuery({ queryKey: ["terms-check", debounced], queryFn: async () => unwrap(await api.POST("/api/v1/agreement-terms/check", { body: debounced })), retry: false });
  return check.data?.valid;
}

function ComponentEditor({ index, value, measure, onChange, onRemove }: { index: number; value: Component; measure: Terms["measure"]; onChange: (c: Component) => void; onRemove?: () => void }) {
  const id = `comp-${index}`;
  const tiered = value.type === "tiered_all_units" || value.type === "tiered_incremental";
  const growth = value.type === "growth_incremental" || value.type === "growth_threshold";
  const perUnitTiers = value.type === "tiered_incremental" ? measure === "quantity" : (value.tiers ?? []).some((t) => t.amount_per_unit != null);
  const set = <K extends keyof Component>(k: K, v: Component[K]) => onChange({ ...value, [k]: v });
  const opt = (s: string) => (s.trim() === "" ? null : s.trim());
  const tiers = value.tiers ?? [];
  return (
    <fieldset className="rounded-md border border-rule p-4">
      <legend className="px-1 text-xs font-semibold text-muted uppercase">Component {index + 1}</legend>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-[2fr_1fr_auto]">
        <Field id={`${id}-type`} label="Type">
          <Select id={`${id}-type`} value={value.type} onChange={(e) => onChange({ key: value.key, type: e.target.value as Component["type"], tiers: [], rate: null, amount_per_unit: null, amount: null, threshold: null, growth_pct: null, baseline_source: e.target.value.startsWith("growth") ? "imported" : null, prior_period_offset: null })}>
            {COMPONENT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </Select>
        </Field>
        <Field id={`${id}-key`} label="Short name"><Input id={`${id}-key`} value={value.key} onChange={(e) => set("key", e.target.value.replace(/[^A-Za-z0-9_.-]/g, ""))} /></Field>
        <div className="flex items-end">{onRemove ? <Button variant="ghost" size="sm" aria-label={`Remove component ${index + 1}`} onClick={onRemove}><Trash2 size={14} aria-hidden="true" /></Button> : null}</div>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        {value.type === "flat_percent" || growth ? <Field id={`${id}-rate`} label="Rate (fraction)" hint="0.02 = 2%"><Input id={`${id}-rate`} inputMode="decimal" value={value.rate ?? ""} onChange={(e) => set("rate", opt(e.target.value))} /></Field> : null}
        {value.type === "per_unit" ? <Field id={`${id}-apu`} label="Amount per unit (USD)"><Input id={`${id}-apu`} inputMode="decimal" value={value.amount_per_unit ?? ""} onChange={(e) => set("amount_per_unit", opt(e.target.value))} /></Field> : null}
        {value.type === "fixed_bonus" ? (
          <>
            <Field id={`${id}-amount`} label="Bonus (USD)"><Input id={`${id}-amount`} inputMode="decimal" value={value.amount ?? ""} onChange={(e) => set("amount", opt(e.target.value))} /></Field>
            <Field id={`${id}-threshold`} label={measure === "spend" ? "When spend reaches (USD)" : "When units reach"}><Input id={`${id}-threshold`} inputMode="decimal" value={value.threshold ?? ""} onChange={(e) => set("threshold", opt(e.target.value))} /></Field>
          </>
        ) : null}
        {value.type === "growth_threshold" ? <Field id={`${id}-growth`} label="Growth target (fraction)" hint="0.10 = 10% over baseline"><Input id={`${id}-growth`} inputMode="decimal" value={value.growth_pct ?? ""} onChange={(e) => set("growth_pct", opt(e.target.value))} /></Field> : null}
        {growth ? (
          <>
            <Field id={`${id}-bsrc`} label="Baseline">
              <Select id={`${id}-bsrc`} value={value.baseline_source ?? "imported"} onChange={(e) => onChange({ ...value, baseline_source: e.target.value as Component["baseline_source"], prior_period_offset: e.target.value === "prior_period_computed" ? "same_period_prior_year" : null })}>
                <option value="imported">Imported baseline file</option><option value="prior_period_computed">Computed from earlier purchases</option>
              </Select>
            </Field>
            {value.baseline_source === "prior_period_computed" ? (
              <Field id={`${id}-offset`} label="Compared with">
                <Select id={`${id}-offset`} value={value.prior_period_offset ?? "same_period_prior_year"} onChange={(e) => set("prior_period_offset", e.target.value as Component["prior_period_offset"])}>
                  <option value="same_period_prior_year">Same period last year</option><option value="immediately_preceding">The previous period</option>
                </Select>
              </Field>
            ) : null}
          </>
        ) : null}
      </div>
      {tiered ? (
        <div className="mt-4">
          {value.type === "tiered_all_units" ? (
            <Checkbox id={`${id}-pu`} label="Tiers pay an amount per unit instead of a %" checked={perUnitTiers} onChange={(e) => set("tiers", tiers.map((t) => ({ threshold: t.threshold, rate: e.target.checked ? null : t.rate ?? "0", amount_per_unit: e.target.checked ? t.amount_per_unit ?? "0" : null })))} />
          ) : <p className="text-xs text-muted">Incremental tiers pay {measure === "spend" ? "a % of spend" : "an amount per unit"} inside each band (matches the measure).</p>}
          <table className="mt-3 w-full text-sm" aria-label={`Tiers of component ${index + 1}`}>
            <thead><tr className="text-left text-xs text-muted"><th className="pb-1">From ({measure === "spend" ? "USD" : "units"})</th><th className="pb-1">{perUnitTiers ? "Amount per unit (USD)" : "Rate (fraction)"}</th><th /></tr></thead>
            <tbody>
              {tiers.map((t, ti) => (
                <tr key={ti}>
                  <td className="py-1 pr-2"><label className="sr-only" htmlFor={`${id}-t${ti}-thr`}>Tier {ti + 1} threshold</label><Input id={`${id}-t${ti}-thr`} inputMode="decimal" value={t.threshold} onChange={(e) => set("tiers", tiers.map((x, j) => (j === ti ? { ...x, threshold: e.target.value.trim() } : x)))} /></td>
                  <td className="py-1 pr-2"><label className="sr-only" htmlFor={`${id}-t${ti}-val`}>Tier {ti + 1} value</label><Input id={`${id}-t${ti}-val`} inputMode="decimal" value={(perUnitTiers ? t.amount_per_unit : t.rate) ?? ""} onChange={(e) => set("tiers", tiers.map((x, j) => (j === ti ? (perUnitTiers ? { ...x, amount_per_unit: e.target.value.trim(), rate: null } : { ...x, rate: e.target.value.trim(), amount_per_unit: null }) : x)))} /></td>
                  <td><Button variant="ghost" size="sm" aria-label={`Remove tier ${ti + 1}`} onClick={() => set("tiers", tiers.filter((_, j) => j !== ti))}><Trash2 size={14} aria-hidden="true" /></Button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <Button variant="secondary" size="sm" className="mt-2" onClick={() => set("tiers", [...tiers, (perUnitTiers ? { threshold: "0", amount_per_unit: "0", rate: null } : { threshold: "0", rate: "0", amount_per_unit: null }) as Tier])}><Plus size={14} aria-hidden="true" /> Add tier</Button>
        </div>
      ) : null}
    </fieldset>
  );
}

function RuleEditor({ index, value, onChange, onRemove }: { index: number; value: Rule; onChange: (r: Rule) => void; onRemove: () => void }) {
  const id = `rule-${index}`;
  return (
    <div className="grid grid-cols-1 items-end gap-3 rounded-md border border-rule p-3 sm:grid-cols-[1fr_1fr_2fr_auto]">
      <Field id={`${id}-action`} label="Action">
        <Select id={`${id}-action`} value={value.action} onChange={(e) => onChange({ ...value, action: e.target.value as Rule["action"] })}>
          <option value="include">Only include</option><option value="exclude">Exclude</option>
        </Select>
      </Field>
      <Field id={`${id}-field`} label="By">
        <Select id={`${id}-field`} value={value.field} onChange={(e) => onChange({ ...value, field: e.target.value as Rule["field"], values: [], flag: e.target.value === "flag" ? "special_pricing" : null, min_amount: e.target.value === "min_line_amount" ? "0" : null, action: e.target.value === "min_line_amount" ? "include" : value.action })}>
          <option value="sku">SKU</option><option value="category">Category</option><option value="branch">Branch</option><option value="flag">Line flag</option><option value="min_line_amount">Minimum line amount</option>
        </Select>
      </Field>
      {value.field === "flag" ? (
        <Field id={`${id}-flag`} label="Flag name" hint="As mapped in imports, e.g. special_pricing"><Input id={`${id}-flag`} value={value.flag ?? ""} onChange={(e) => onChange({ ...value, flag: e.target.value.trim() })} /></Field>
      ) : value.field === "min_line_amount" ? (
        <Field id={`${id}-min`} label="At least (USD, absolute)"><Input id={`${id}-min`} inputMode="decimal" value={value.min_amount ?? ""} onChange={(e) => onChange({ ...value, min_amount: e.target.value.trim() })} /></Field>
      ) : (
        <Field id={`${id}-values`} label="Values (comma-separated)"><Input id={`${id}-values`} value={(value.values ?? []).join(", ")} onChange={(e) => onChange({ ...value, values: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) })} /></Field>
      )}
      <Button variant="ghost" size="sm" aria-label={`Remove rule ${index + 1}`} onClick={onRemove}><Trash2 size={14} aria-hidden="true" /></Button>
    </div>
  );
}

function CustomPeriods({ value, onChange }: { value: Terms; onChange: (t: Terms) => void }) {
  const periods = value.custom_periods ?? [];
  const set = (p: typeof periods) => onChange({ ...value, custom_periods: p });
  return (
    <div className="mt-4">
      <p className="mb-2 text-sm font-medium">Custom periods</p>
      {periods.map((p, i) => (
        <div key={i} className="mb-2 grid grid-cols-[1fr_1fr_1fr_auto] items-end gap-2">
          <Field id={`cp-${i}-s`} label="Start"><Input id={`cp-${i}-s`} type="date" value={p.start} onChange={(e) => set(periods.map((x, j) => (j === i ? { ...x, start: e.target.value } : x)))} /></Field>
          <Field id={`cp-${i}-e`} label="End"><Input id={`cp-${i}-e`} type="date" value={p.end} onChange={(e) => set(periods.map((x, j) => (j === i ? { ...x, end: e.target.value } : x)))} /></Field>
          <Field id={`cp-${i}-l`} label="Label"><Input id={`cp-${i}-l`} value={p.label ?? ""} onChange={(e) => set(periods.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} /></Field>
          <Button variant="ghost" size="sm" aria-label={`Remove period ${i + 1}`} onClick={() => set(periods.filter((_, j) => j !== i))}><Trash2 size={14} aria-hidden="true" /></Button>
        </div>
      ))}
      <Button variant="secondary" size="sm" onClick={() => set([...periods, { start: value.effective_from, end: value.effective_from, label: `P${periods.length + 1}` }])}><Plus size={14} aria-hidden="true" /> Add period</Button>
    </div>
  );
}
