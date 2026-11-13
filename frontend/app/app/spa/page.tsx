"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Card, Field, Input, Notice, PageHeader, Select, Textarea } from "@/components/ui/core";
import { DateText, Money, StatusBadge } from "@/components/ui/finance";
import { Dialog, Drawer, Tabs } from "@/components/ui/overlay";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, idempotencyKey, unwrap } from "@/lib/api";
import { formatDate, formatQuantity } from "@/lib/format";
import { fetchAllSuppliers } from "@/lib/queries";
import { can, useSession } from "@/lib/session";
import type { components } from "@/generated/api";

type Match = components["schemas"]["SpaMatchOut"];
type Claim = components["schemas"]["SpaClaimOut"];
type SpaItemIn = components["schemas"]["SpaItemIn"];

/** Ship-and-debit / SPA claims (v1.1 Phase 17). */
export default function SpaPage() {
  const session = useSession();
  return (
    <>
      <PageHeader
        title="SPA claims"
        description="Special pricing agreements: what suppliers owe you back for sales made at the agreed price, which lines are claimable, and your claims."
        actions={<Link href="/app/imports/new?type=sales" className="text-sm text-brand hover:underline">Import sales lines →</Link>}
      />
      <Tabs
        label="SPA sections"
        tabs={[
          { value: "overview", label: "Overview", content: <Overview canRerun={can(session, "run_reconciliation")} /> },
          { value: "lines", label: "Lines", content: <Lines /> },
          { value: "spas", label: "SPAs", content: <SpaList editable={can(session, "edit_agreements")} /> },
          { value: "claims", label: "Claims", content: <Claims editable={can(session, "edit_claims")} /> },
        ]}
      />
    </>
  );
}

function Overview({ canRerun }: { canRerun: boolean }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["spa-summary"], queryFn: async () => unwrap(await api.GET("/api/v1/spa/summary")) });
  const rerun = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/spa/recalculate")),
    onSuccess: () => { toast.success("Matching started"); setTimeout(() => void qc.invalidateQueries({ queryKey: ["spa-summary"] }), 1500); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="By supplier" actions={canRerun ? <Button variant="secondary" size="sm" loading={rerun.isPending} onClick={() => rerun.mutate()}>Match again</Button> : undefined}>
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No SPA lines yet">Add your SPAs, then import sales lines.</EmptyState>}>
        {(rows) => (
          <table className="w-full text-sm" aria-label="SPA summary by supplier">
            <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th scope="col" className="py-2">Supplier</th><th scope="col" className="num">Claimable, not claimed</th><th scope="col" className="num">Lines</th><th scope="col" className="num">Needs review</th><th scope="col" className="num">Deadline within 14 days</th><th scope="col" className="num">Past deadline</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.supplier_id} className="border-b border-rule last:border-0">
                  <td className="py-2">{r.supplier_name}</td>
                  <td className="num font-medium"><Money value={r.unclaimed_amount} /></td>
                  <td className="num">{r.unclaimed_lines}</td>
                  <td className="num">{r.needs_review_lines}</td>
                  <td className={`num ${r.expiring_soon_lines ? "font-medium text-warning" : ""}`}>{r.expiring_soon_lines}</td>
                  <td className={`num ${r.past_deadline_lines ? "font-medium text-negative" : ""}`}>{r.past_deadline_lines}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
    </Card>
  );
}

const STATUS_LABEL: Record<string, string> = { ok: "Claimable", needs_review: "Needs review", not_claimable: "Not claimable" };

function MatchTable({ rows, label }: { rows: Match[]; label: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label={label}>
        <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th scope="col" className="py-2">Invoice</th><th scope="col">Date</th><th scope="col">Customer / job</th><th scope="col">SKU</th><th scope="col" className="num">Qty</th><th scope="col">SPA</th><th scope="col">Status</th><th scope="col" className="num">Claimable</th><th scope="col">Deadline</th></tr></thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.sale_line_id} className="border-b border-rule align-top last:border-0">
              <td className="py-2 font-mono text-xs">{m.invoice_number}{m.line_number ? `/${m.line_number}` : ""}</td>
              <td><DateText value={m.invoice_date} /></td>
              <td>{m.customer ?? "—"}{m.job ? <span className="block text-xs text-muted">{m.job}</span> : null}</td>
              <td className="font-mono text-xs">{m.sku}</td>
              <td className="num">{formatQuantity(m.claimable_quantity)}<span className="block text-xs text-muted">of {formatQuantity(m.quantity)}</span></td>
              <td>{m.spa_number ?? "—"}</td>
              <td>
                {STATUS_LABEL[m.status] ?? m.status}
                {m.reasons.map((r) => <span key={r.code} className="block text-xs text-muted">{r.message}</span>)}
              </td>
              <td className="num"><Money value={m.claimable_amount} /></td>
              <td>{m.deadline ? formatDate(m.deadline) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Lines() {
  const [status, setStatus] = useState<"ok" | "needs_review" | "not_claimable">("needs_review");
  const query = useQuery({
    queryKey: ["spa-matches", status],
    queryFn: async () => unwrap(await api.GET("/api/v1/spa/matches", { params: { query: { status, unclaimed: true, limit: 500 } } })),
  });
  return (
    <Card title="Unclaimed lines">
      <Field id="spa-status" label="Show" className="mb-4 max-w-xs">
        <Select id="spa-status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
          <option value="needs_review">Needs review</option>
          <option value="ok">Claimable</option>
          <option value="not_claimable">Not claimable (cap used up)</option>
        </Select>
      </Field>
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="Nothing here">No unclaimed lines with this status.</EmptyState>}>
        {(rows) => <MatchTable rows={rows} label="Unclaimed SPA lines" />}
      </QueryState>
    </Card>
  );
}

/** Parse "SKU, book cost, SPA cost[, cap]" lines. Values stay decimal strings (no JS arithmetic). */
function parseItems(text: string): { items: SpaItemIn[]; errors: string[] } {
  const items: SpaItemIn[] = [];
  const errors: string[] = [];
  const dec = /^\d+(\.\d{1,4})?$/;
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = raw.trim();
    if (!line) return;
    const [sku, book, spa, cap] = line.split(",").map((x) => x.trim());
    if (!sku || !book || !spa || !dec.test(book) || !dec.test(spa) || (cap !== undefined && cap !== "" && !dec.test(cap))) {
      errors.push(`Line ${i + 1}: expected "SKU, book cost, SPA cost, optional cap" with plain numbers.`);
      return;
    }
    items.push({ sku, book_cost: book, spa_cost: spa, quantity_cap: cap ? cap : null });
  });
  return { items, errors };
}

function SpaList({ editable }: { editable: boolean }) {
  const [creating, setCreating] = useState(false);
  const query = useQuery({ queryKey: ["spas"], queryFn: async () => unwrap(await api.GET("/api/v1/spas")) });
  const suppliers = useQuery({ queryKey: ["suppliers", "all"], queryFn: fetchAllSuppliers });
  const names = new Map((suppliers.data ?? []).map((s) => [s.id, s.name]));
  return (
    <Card title="Special pricing agreements" actions={editable ? <Button size="sm" onClick={() => setCreating(true)}>Add SPA</Button> : undefined}>
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No SPAs yet">Add the SPAs your suppliers granted, with their book and SPA costs.</EmptyState>}>
        {(rows) => (
          <table className="w-full text-sm" aria-label="SPAs">
            <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th scope="col" className="py-2">SPA</th><th scope="col">Supplier</th><th scope="col">Customer / job</th><th scope="col">Valid</th><th scope="col" className="num">Claim within (days)</th><th scope="col" className="num">Items</th><th scope="col">Status</th></tr></thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-b border-rule last:border-0">
                  <td className="py-2 font-medium">{s.spa_number}</td>
                  <td>{names.get(s.supplier_id) ?? "—"}</td>
                  <td>{s.customer ?? "Any customer"}{s.job ? <span className="block text-xs text-muted">{s.job}</span> : null}</td>
                  <td>{formatDate(s.valid_from)} – {formatDate(s.valid_to)}</td>
                  <td className="num">{s.claim_deadline_days}</td>
                  <td className="num">{s.items.length}</td>
                  <td><StatusBadge status={s.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
      <NewSpa open={creating} onOpenChange={setCreating} />
    </Card>
  );
}

function NewSpa({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const suppliers = useQuery({ queryKey: ["suppliers", "all"], queryFn: fetchAllSuppliers, enabled: open });
  const [f, setF] = useState({ supplier_id: "", spa_number: "", customer: "", job: "", valid_from: "", valid_to: "", claim_deadline_days: "60", items: "" });
  const parsed = parseItems(f.items);
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/spas", {
          body: {
            supplier_id: f.supplier_id, spa_number: f.spa_number.trim(), customer: f.customer.trim() || null, job: f.job.trim() || null,
            valid_from: f.valid_from, valid_to: f.valid_to, claim_deadline_days: Number.parseInt(f.claim_deadline_days, 10), status: "active", notes: "", items: parsed.items,
          },
        }),
      ),
    onSuccess: () => { toast.success("SPA saved; matching your sales lines"); onOpenChange(false); void qc.invalidateQueries({ queryKey: ["spas"] }); void qc.invalidateQueries({ queryKey: ["spa-summary"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const ready = f.supplier_id && f.spa_number.trim() && f.valid_from && f.valid_to && /^\d+$/.test(f.claim_deadline_days) && parsed.items.length > 0 && parsed.errors.length === 0;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add SPA" wide footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!ready} loading={create.isPending} onClick={() => create.mutate()}>Save SPA</Button></>}>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field id="spa-supplier" label="Supplier" required>
          <Select id="spa-supplier" value={f.supplier_id} onChange={set("supplier_id")}>
            <option value="">Choose…</option>
            {(suppliers.data ?? []).filter((s) => s.kind === "supplier").map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <Field id="spa-number" label="SPA number" required><Input id="spa-number" value={f.spa_number} onChange={set("spa_number")} maxLength={100} /></Field>
        <Field id="spa-customer" label="Customer" hint="Leave empty if any customer qualifies."><Input id="spa-customer" value={f.customer} onChange={set("customer")} maxLength={200} /></Field>
        <Field id="spa-job" label="Job / project" hint="Optional."><Input id="spa-job" value={f.job} onChange={set("job")} maxLength={200} /></Field>
        <Field id="spa-from" label="Valid from" required><Input id="spa-from" type="date" value={f.valid_from} onChange={set("valid_from")} /></Field>
        <Field id="spa-to" label="Valid to" required><Input id="spa-to" type="date" value={f.valid_to} onChange={set("valid_to")} /></Field>
        <Field id="spa-days" label="Claim within (days after the sale)" required><Input id="spa-days" inputMode="numeric" value={f.claim_deadline_days} onChange={set("claim_deadline_days")} /></Field>
        <Field id="spa-items" label="Items" required className="sm:col-span-2" hint="One per line: SKU, book cost, SPA cost, optional quantity cap. Example: WIRE-12, 10.00, 7.50, 500">
          <Textarea id="spa-items" className="font-mono" rows={6} value={f.items} onChange={set("items")} />
        </Field>
      </div>
      {parsed.errors.length ? <div className="mt-3"><Notice tone="warning"><ul className="list-disc pl-4">{parsed.errors.map((e) => <li key={e}>{e}</li>)}</ul></Notice></div> : null}
    </Dialog>
  );
}

function Claims({ editable }: { editable: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState<Claim | null>(null);
  const [making, setMaking] = useState(false);
  const query = useQuery({ queryKey: ["spa-claims"], queryFn: async () => unwrap(await api.GET("/api/v1/spa-claims")) });
  const suppliers = useQuery({ queryKey: ["suppliers", "all"], queryFn: fetchAllSuppliers });
  const names = new Map((suppliers.data ?? []).map((s) => [s.id, s.name]));
  const [form, setForm] = useState({ supplier_id: "", through_date: new Date().toISOString().slice(0, 10) });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/spa-claims", { body: form, headers: { "Idempotency-Key": idempotencyKey() } })),
    onSuccess: (c) => { toast.success(`Claim SPA-CL-${String(c.number).padStart(4, "0")} created`); setMaking(false); void qc.invalidateQueries({ queryKey: ["spa-claims"] }); void qc.invalidateQueries({ queryKey: ["spa-summary"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Claims" actions={editable ? <Button size="sm" onClick={() => setMaking(true)}>New claim</Button> : undefined}>
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No claims yet">Create a claim from the claimable lines of a supplier.</EmptyState>}>
        {(rows) => (
          <table className="w-full text-sm" aria-label="SPA claims">
            <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th scope="col" className="py-2">Claim</th><th scope="col">Supplier</th><th scope="col">Status</th><th scope="col" className="num">Lines</th><th scope="col" className="num">Claimed</th><th scope="col" className="num">Paid</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-b border-rule last:border-0">
                  <td className="py-2"><button type="button" className="font-medium text-brand hover:underline" onClick={() => setOpen(c)}>SPA-CL-{String(c.number).padStart(4, "0")}</button></td>
                  <td>{names.get(c.supplier_id) ?? "—"}</td>
                  <td><StatusBadge status={c.status} /></td>
                  <td className="num">{c.line_count}</td>
                  <td className="num"><Money value={c.total} /></td>
                  <td className="num">{c.paid_amount ? <Money value={c.paid_amount} /> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
      <Dialog open={making} onOpenChange={setMaking} title="New SPA claim" description="Includes every claimable, unclaimed line of the supplier dated on or before the date." footer={<><Button variant="secondary" onClick={() => setMaking(false)}>Cancel</Button><Button disabled={!form.supplier_id} loading={create.isPending} onClick={() => create.mutate()}>Create claim</Button></>}>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field id="claim-supplier" label="Supplier" required>
            <Select id="claim-supplier" value={form.supplier_id} onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}>
              <option value="">Choose…</option>
              {(suppliers.data ?? []).filter((s) => s.kind === "supplier").map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
          <Field id="claim-through" label="Sales up to" required><Input id="claim-through" type="date" value={form.through_date} onChange={(e) => setForm({ ...form, through_date: e.target.value })} /></Field>
        </div>
      </Dialog>
      <ClaimDrawer claim={open} onClose={() => setOpen(null)} editable={editable} />
    </Card>
  );
}

function ClaimDrawer({ claim, onClose, editable }: { claim: Claim | null; onClose: () => void; editable: boolean }) {
  const qc = useQueryClient();
  const [pay, setPay] = useState({ paid_amount: "", credit_reference: "" });
  const detail = useQuery({
    queryKey: ["spa-claim", claim?.id],
    enabled: !!claim,
    queryFn: async () => {
      const r = await api.GET("/api/v1/spa-claims/{claim_id}", { params: { path: { claim_id: claim!.id } } });
      return { data: unwrap(r), etag: r.response.headers.get("ETag") ?? "" };
    },
  });
  const lines = useQuery({ queryKey: ["spa-claim-lines", claim?.id], enabled: !!claim, queryFn: async () => unwrap(await api.GET("/api/v1/spa-claims/{claim_id}/lines", { params: { path: { claim_id: claim!.id } } })) });
  const move = useMutation({
    mutationFn: async (to: "submitted" | "paid" | "rejected") =>
      unwrap(
        await api.POST("/api/v1/spa-claims/{claim_id}/transition", {
          params: { path: { claim_id: claim!.id } },
          headers: { "If-Match": detail.data?.etag ?? "" },
          body: to === "paid" ? { to, paid_amount: pay.paid_amount, credit_reference: pay.credit_reference } : { to, credit_reference: "" },
        }),
      ),
    onSuccess: (c) => { toast.success(`Claim is now ${c.status.replace("_", " ")}`); setPay({ paid_amount: "", credit_reference: "" }); void qc.invalidateQueries({ queryKey: ["spa-claims"] }); void qc.invalidateQueries({ queryKey: ["spa-claim", claim?.id] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const c = detail.data?.data ?? claim;
  return (
    <Drawer open={claim !== null} onOpenChange={(o) => !o && onClose()} title={c ? `SPA-CL-${String(c.number).padStart(4, "0")}` : "Claim"} description={c ? <>Claimed <Money value={c.total} /> · {c.line_count} lines · {c.status.replace("_", " ")}</> : undefined}>
      {c ? (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <a className="text-sm text-brand underline" href={`/api/v1/spa-claims/${c.id}/evidence.csv`} download>Download evidence (CSV)</a>
          </div>
          {editable && c.status === "draft" ? <div className="flex gap-2"><Button onClick={() => move.mutate("submitted")} loading={move.isPending}>Mark submitted</Button><Button variant="secondary" onClick={() => move.mutate("rejected")}>Withdraw</Button></div> : null}
          {editable && (c.status === "submitted" || c.status === "partially_paid") ? (
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); move.mutate("paid"); }}>
              <Field id="pay-amount" label="Amount paid ($)"><Input id="pay-amount" inputMode="decimal" value={pay.paid_amount} onChange={(e) => setPay({ ...pay, paid_amount: e.target.value })} /></Field>
              <Field id="pay-ref" label="Credit memo reference"><Input id="pay-ref" value={pay.credit_reference} maxLength={100} onChange={(e) => setPay({ ...pay, credit_reference: e.target.value })} /></Field>
              <Button type="submit" disabled={!/^\d+(\.\d{1,2})?$/.test(pay.paid_amount) || !pay.credit_reference.trim()} loading={move.isPending}>Record payment</Button>
              {c.status === "submitted" ? <Button variant="secondary" onClick={() => move.mutate("rejected")}>Rejected by supplier</Button> : null}
            </form>
          ) : null}
          <QueryState query={lines}>{(rows) => <MatchTable rows={rows} label="Lines in this claim" />}</QueryState>
        </div>
      ) : null}
    </Drawer>
  );
}
