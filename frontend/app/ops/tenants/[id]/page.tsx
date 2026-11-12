"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Card, Checkbox, Field, Input, Notice, PageHeader, Select } from "@/components/ui/core";
import { DateText, Money, StatusBadge } from "@/components/ui/finance";
import { QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { components } from "@/generated/api";

type Detail = components["schemas"]["TenantDetail"];
type SubIn = components["schemas"]["SubscriptionIn"];
const STATUSES = ["pilot", "active", "past_due", "suspended", "cancelled"] as const;
const MONEY_RE = /^\d{1,14}(\.\d{1,4})?$/;

export default function OpsTenantPage() {
  const { id } = useParams<{ id: string }>();
  const query = useQuery({ queryKey: ["ops", "tenant", id], queryFn: async () => unwrap(await api.GET("/api/v1/ops/tenants/{tenant_id}", { params: { path: { tenant_id: id } } })) });
  return <QueryState query={query}>{(t) => <TenantView t={t} />}</QueryState>;
}

function TenantView({ t }: { t: Detail }) {
  const qc = useQueryClient();
  const router = useRouter();
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops"] });
  const activeGrant = t.grants.find((g) => !g.revoked_at && new Date(g.expires_at) > new Date());
  const enter = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/ops/support/enter", { body: { tenant_id: t.id } })),
    onSuccess: async () => { await qc.invalidateQueries(); router.push("/app"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <>
      <PageHeader
        title={t.name}
        description={<>{t.plan ?? "No plan"} · created {formatDateTime(t.created_at)} · {t.timezone}</>}
        actions={<Button variant="secondary" disabled={!activeGrant} loading={enter.isPending} onClick={() => enter.mutate()} title={activeGrant ? undefined : "The organization has not granted support access"}>Enter support session</Button>}
      >
        <div className="mt-2">{t.status ? <StatusBadge status={t.status} /> : null}</div>
      </PageHeader>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card title="Usage (aggregate)">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            {[["Members", t.members], ["Active agreements", t.active_agreements], ["Purchase lines", t.purchase_lines.toLocaleString("en-US")], ["Open claims", t.open_claims]].map(([k, v]) => (
              <div key={String(k)}><dt className="text-xs text-muted">{k}</dt><dd className="text-lg font-semibold">{v}</dd></div>
            ))}
            <div><dt className="text-xs text-muted">Last import</dt><dd>{t.last_import_at ? formatDateTime(t.last_import_at) : "—"}</dd></div>
            <div><dt className="text-xs text-muted">Last run</dt><dd>{t.last_run_at ? formatDateTime(t.last_run_at) : "—"}</dd></div>
          </dl>
        </Card>
        <SubscriptionCard t={t} onSaved={refresh} />
        <Card title="Members">
          <ul className="divide-y divide-rule text-sm">
            {t.members_list.map((m) => <li key={m.email} className="flex justify-between py-1.5"><span>{m.name || m.email} <span className="text-xs text-muted">{m.email}</span></span><span className="text-xs capitalize text-muted">{m.role} · {m.status}</span></li>)}
          </ul>
        </Card>
        <Card title="Support access granted by the organization">
          {t.grants.length === 0 ? <p className="text-sm text-muted">Never granted.</p> : (
            <ul className="divide-y divide-rule text-sm">
              {t.grants.map((g) => (
                <li key={g.id} className="py-1.5">
                  {g.scope.replace("_", "-")} · {formatDateTime(g.created_at)} → {formatDateTime(g.expires_at)}
                  {g.revoked_at ? <span className="ml-2 text-xs text-muted">revoked</span> : g === activeGrant ? <span className="ml-2 text-xs text-positive">active</span> : <span className="ml-2 text-xs text-muted">expired</span>}
                  {g.reason ? <p className="text-xs text-muted">{g.reason}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <FlagsCard t={t} onSaved={refresh} />
        <InvoiceDraft tenantId={t.id} />
      </div>
    </>
  );
}

function SubscriptionCard({ t, onSaved }: { t: Detail; onSaved: () => void }) {
  const plans = useQuery({ queryKey: ["ops", "plans"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/plans")) });
  const sub = t.subscription;
  const currentPlan = (plans.data ?? []).find((p) => p.id === sub?.plan_id)?.code ?? "";
  const [f, setF] = useState<{ plan_code: string; status: string; billing_contact_name: string; billing_contact_email: string; term_end: string }>({
    plan_code: "", status: sub?.status ?? "pilot", billing_contact_name: sub?.billing_contact_name ?? "", billing_contact_email: sub?.billing_contact_email ?? "", term_end: sub?.term_end ?? "",
  });
  const save = useMutation({
    mutationFn: async () => {
      const body: SubIn = { status: f.status as SubIn["status"], billing_contact_name: f.billing_contact_name, term_end: f.term_end || null };
      if (f.billing_contact_email) body.billing_contact_email = f.billing_contact_email;
      if (f.plan_code && f.plan_code !== currentPlan) body.plan_code = f.plan_code;
      return unwrap(await api.PATCH("/api/v1/ops/tenants/{tenant_id}/subscription", { params: { path: { tenant_id: t.id } }, body }));
    },
    onSuccess: () => { toast.success("Subscription saved"); onSaved(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!sub) return <Card title="Subscription"><Notice tone="warning">This organization has no subscription.</Notice></Card>;
  return (
    <Card title="Subscription">
      {f.status === "suspended" ? <div className="mb-3"><Notice tone="warning">Suspended organizations are read-only: they can view and export, but not import, run or edit. Data is never deleted.</Notice></div> : null}
      {sub.past_due_since ? <p className="mb-3 text-sm text-warning">Past due since <DateText value={sub.past_due_since} />.</p> : null}
      <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <Field id="s-plan" label="Plan">
          <Select id="s-plan" value={f.plan_code || currentPlan} onChange={(e) => setF({ ...f, plan_code: e.target.value })}>
            {(plans.data ?? []).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
          </Select>
        </Field>
        <Field id="s-status" label="Status">
          <Select id="s-status" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
            {STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </Select>
        </Field>
        <Field id="s-bname" label="Billing contact"><Input id="s-bname" value={f.billing_contact_name} maxLength={200} onChange={(e) => setF({ ...f, billing_contact_name: e.target.value })} /></Field>
        <Field id="s-bemail" label="Billing email"><Input id="s-bemail" type="email" value={f.billing_contact_email} onChange={(e) => setF({ ...f, billing_contact_email: e.target.value })} /></Field>
        <Field id="s-end" label="Term ends"><Input id="s-end" type="date" value={f.term_end} onChange={(e) => setF({ ...f, term_end: e.target.value })} /></Field>
        <div className="flex items-end"><Button type="submit" loading={save.isPending}>Save subscription</Button></div>
      </form>
    </Card>
  );
}

function FlagsCard({ t, onSaved }: { t: Detail; onSaved: () => void }) {
  const catalog = useQuery({ queryKey: ["ops", "flags"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/feature-flags")) });
  const set = useMutation({
    mutationFn: async ({ key, enabled }: { key: string; enabled: boolean }) => unwrap(await api.PUT("/api/v1/ops/tenants/{tenant_id}/flags", { params: { path: { tenant_id: t.id } }, body: { key, enabled } })),
    onSuccess: () => onSaved(),
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Feature flags">
      <div className="flex flex-col gap-2">
        {Object.entries(catalog.data ?? {}).map(([key, label]) => (
          <Checkbox key={key} id={`flag-${key}`} label={<>{label} <span className="font-mono text-xs text-muted">{key}</span></>} checked={t.flags[key] ?? false} disabled={set.isPending} onChange={(e) => set.mutate({ key, enabled: e.target.checked })} />
        ))}
      </div>
    </Card>
  );
}

function InvoiceDraft({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const invoices = useQuery({ queryKey: ["ops", "invoices", tenantId], queryFn: async () => unwrap(await api.GET("/api/v1/ops/invoices", { params: { query: { tenant_id: tenantId } } })) });
  const [lines, setLines] = useState([{ description: "", quantity: "1", unit_price: "" }]);
  const [period, setPeriod] = useState({ start: "", end: "" });
  const invalid = lines.some((l) => !l.description.trim() || !MONEY_RE.test(l.quantity) || !MONEY_RE.test(l.unit_price));
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/ops/invoices", { body: { tenant_id: tenantId, period_start: period.start || null, period_end: period.end || null, notes: "", lines } })),
    onSuccess: () => { toast.success("Draft saved — issue it from Invoices"); setLines([{ description: "", quantity: "1", unit_price: "" }]); void qc.invalidateQueries({ queryKey: ["ops", "invoices"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Invoices">
      <ul className="mb-4 divide-y divide-rule text-sm">
        {(invoices.data ?? []).map((i) => (
          <li key={i.id} className="flex items-center justify-between py-1.5">
            <Link href={`/ops/invoices?open=${i.id}`} className="font-mono hover:underline">{i.number ?? "Draft"}</Link>
            <span className="flex items-center gap-3"><StatusBadge status={i.status} /><Money value={i.total} /></span>
          </li>
        ))}
        {invoices.data?.length === 0 ? <li className="py-1.5 text-muted">No invoices yet.</li> : null}
      </ul>
      <h3 className="mb-2 text-sm font-semibold">New draft</h3>
      <div className="mb-2 grid grid-cols-2 gap-2">
        <Field id="inv-ps" label="Service from"><Input id="inv-ps" type="date" value={period.start} onChange={(e) => setPeriod({ ...period, start: e.target.value })} /></Field>
        <Field id="inv-pe" label="Service to"><Input id="inv-pe" type="date" value={period.end} onChange={(e) => setPeriod({ ...period, end: e.target.value })} /></Field>
      </div>
      {lines.map((l, i) => (
        <div key={i} className="mb-2 grid grid-cols-[1fr_80px_120px] gap-2">
          <Field id={`l-d-${i}`} label="Description"><Input id={`l-d-${i}`} value={l.description} maxLength={300} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} /></Field>
          <Field id={`l-q-${i}`} label="Qty"><Input id={`l-q-${i}`} inputMode="decimal" value={l.quantity} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, quantity: e.target.value.trim() } : x)))} /></Field>
          <Field id={`l-p-${i}`} label="Unit price ($)"><Input id={`l-p-${i}`} inputMode="decimal" className="text-right" value={l.unit_price} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, unit_price: e.target.value.trim() } : x)))} /></Field>
        </div>
      ))}
      <div className="flex gap-2">
        <Button size="sm" variant="secondary" onClick={() => setLines([...lines, { description: "", quantity: "1", unit_price: "" }])}>Add line</Button>
        <Button size="sm" onClick={() => create.mutate()} disabled={invalid} loading={create.isPending}>Save draft</Button>
      </div>
      <p className="mt-2 text-xs text-muted">The total is computed by the server. No tax is calculated in this version.</p>
    </Card>
  );
}
