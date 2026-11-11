"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { SupplierForm } from "@/components/supplier-form";
import { Button, Card, Field, Input, PageHeader, Select } from "@/components/ui/core";
import { DateText, Money, StatusBadge } from "@/components/ui/finance";
import { ConfirmDialog, Dialog, Tabs } from "@/components/ui/overlay";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { can, useSession } from "@/lib/session";
import { fetchAllSuppliers } from "@/lib/queries";

export default function SupplierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const session = useSession();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [merging, setMerging] = useState(false);
  const query = useQuery({
    queryKey: ["supplier", id],
    queryFn: async () => {
      const r = await api.GET("/api/v1/suppliers/{supplier_id}", { params: { path: { supplier_id: id } } });
      return { data: unwrap(r), etag: r.response.headers.get("ETag") ?? "" };
    },
  });
  const editable = can(session, "edit_suppliers");
  return (
    <QueryState query={query}>
      {({ data: s, etag }) => (
        <>
          <PageHeader
            title={s.name}
            description={<span className="font-mono text-xs">{s.codes.join(" · ")}</span>}
            actions={editable ? (
              <>
                <Button variant="secondary" onClick={() => setEditing(true)}>Edit</Button>
                <Button variant="secondary" onClick={() => setMerging(true)}>Merge into…</Button>
              </>
            ) : undefined}
          >
            <div className="mt-2 flex items-center gap-2"><StatusBadge status={s.status} />{s.category_tags.map((t) => <span key={t} className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">{t}</span>)}</div>
          </PageHeader>
          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Card title="Latest purchase imported"><p className="text-lg font-semibold">{s.latest_purchase_date ? <DateText value={s.latest_purchase_date} /> : "No purchases yet"}</p></Card>
            <Card title="Latest credit imported"><p className="text-lg font-semibold">{s.latest_credit_date ? <DateText value={s.latest_credit_date} /> : "No credits yet"}</p></Card>
            <Card title="Agreements"><p className="text-lg font-semibold num text-left">{s.agreement_count}</p></Card>
          </div>
          <Tabs
            label="Supplier sections"
            tabs={[
              { value: "agreements", label: "Agreements", content: <SupplierAgreements supplierId={s.id} /> },
              { value: "results", label: "Latest results", content: <SupplierResults supplierId={s.id} /> },
              { value: "claims", label: "Claims", content: <SupplierClaims supplierId={s.id} /> },
              { value: "contacts", label: "Contacts", content: <Contacts supplierId={s.id} editable={editable} /> },
              { value: "notes", label: "Notes", content: <Card><p className="text-sm whitespace-pre-wrap">{s.payment_notes || "No payment notes."}</p><p className="mt-3 text-sm whitespace-pre-wrap text-muted">{s.notes}</p></Card> },
            ]}
          />
          <Dialog open={editing} onOpenChange={setEditing} title={`Edit ${s.name}`} wide>
            <SupplierForm
              submitLabel="Save"
              initial={{ name: s.name, codes: s.codes.join(", "), category_tags: s.category_tags.join(", "), payment_notes: s.payment_notes, notes: s.notes }}
              onSubmit={async (body) => {
                unwrap(await api.PATCH("/api/v1/suppliers/{supplier_id}", { params: { path: { supplier_id: s.id } }, body, headers: { "If-Match": etag } }));
                setEditing(false);
                toast.success("Supplier saved");
                await qc.invalidateQueries({ queryKey: ["supplier", id] });
              }}
            />
          </Dialog>
          <MergeDialog open={merging} onOpenChange={setMerging} sourceId={s.id} sourceName={s.name} />
        </>
      )}
    </QueryState>
  );
}

function SupplierAgreements({ supplierId }: { supplierId: string }) {
  const query = useQuery({ queryKey: ["agreements", "supplier", supplierId], queryFn: async () => unwrap(await api.GET("/api/v1/agreements", { params: { query: { supplier_id: supplierId, limit: 200 } } })).items });
  return (
    <QueryState query={query} isEmpty={(a) => a.length === 0} empty={<EmptyState title="No agreements" action={<Link className="text-brand hover:underline" href="/app/agreements/new">Add an agreement</Link>} />}>
      {(rows) => (
        <ul className="divide-y divide-rule rounded-lg border border-rule bg-surface">
          {rows.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
              <div className="min-w-0"><Link href={`/app/agreements/${a.id}`} className="font-medium hover:underline">{a.name}</Link><p className="truncate text-xs text-muted">{a.summary}</p></div>
              <StatusBadge status={a.latest_version_status ?? a.status} />
            </li>
          ))}
        </ul>
      )}
    </QueryState>
  );
}

function SupplierResults({ supplierId }: { supplierId: string }) {
  const query = useQuery({ queryKey: ["reconciliation", { supplierId }], queryFn: async () => unwrap(await api.GET("/api/v1/reconciliation", { params: { query: { supplier_id: supplierId } } })) });
  return (
    <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No results yet">Start a run to calculate this supplier&rsquo;s rebates.</EmptyState>}>
      {(rows) => (
        <table className="w-full text-sm" aria-label="Latest results">
          <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th className="py-2">Agreement</th><th>Period</th><th className="text-right">Expected</th><th className="text-right">Received</th><th>Status</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.result_id} className="border-b border-rule last:border-0"><td className="py-2">{r.agreement_name}</td><td><DateText value={r.period_start} /> – <DateText value={r.period_end} /></td><td className="text-right"><Money value={r.expected} /></td><td className="text-right"><Money value={r.received} /></td><td><StatusBadge status={r.status} /></td></tr>
          ))}</tbody>
        </table>
      )}
    </QueryState>
  );
}

function SupplierClaims({ supplierId }: { supplierId: string }) {
  const query = useQuery({ queryKey: ["claims", { supplierId }], queryFn: async () => unwrap(await api.GET("/api/v1/claims", { params: { query: { supplier_id: supplierId, open: true } } })).items });
  return (
    <QueryState query={query} isEmpty={(c) => c.length === 0} empty={<EmptyState title="No open claims" />}>
      {(rows) => (
        <ul className="divide-y divide-rule rounded-lg border border-rule bg-surface">
          {rows.map((c) => <li key={c.id} className="flex items-center justify-between px-4 py-3 text-sm"><Link href={`/app/claims/${c.id}`} className="hover:underline">CL-{String(c.number).padStart(4, "0")} · {c.title}</Link><span className="flex items-center gap-3"><Money value={c.claimed_amount} /><StatusBadge status={c.status} /></span></li>)}
        </ul>
      )}
    </QueryState>
  );
}

function Contacts({ supplierId, editable }: { supplierId: string; editable: boolean }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: "", email: "", phone: "", role: "" });
  const [removing, setRemoving] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["contacts", supplierId], queryFn: async () => unwrap(await api.GET("/api/v1/suppliers/{supplier_id}/contacts", { params: { path: { supplier_id: supplierId } } })) });
  const add = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/suppliers/{supplier_id}/contacts", { params: { path: { supplier_id: supplierId } }, body: form })),
    onSuccess: () => { setForm({ name: "", email: "", phone: "", role: "" }); void qc.invalidateQueries({ queryKey: ["contacts", supplierId] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: async (cid: string) => unwrap(await api.DELETE("/api/v1/suppliers/contacts/{contact_id}", { params: { path: { contact_id: cid } } })),
    onSuccess: () => { setRemoving(null); void qc.invalidateQueries({ queryKey: ["contacts", supplierId] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card>
      <QueryState query={query} isEmpty={(c) => c.length === 0} empty={<p className="mb-4 text-sm text-muted">No contacts yet.</p>}>
        {(rows) => (
          <ul className="mb-4 divide-y divide-rule">
            {rows.map((c) => (
              <li key={c.id} className="flex items-center justify-between py-2 text-sm">
                <span><strong>{c.name}</strong>{c.role ? ` · ${c.role}` : ""}<span className="block text-xs text-muted">{[c.email, c.phone].filter(Boolean).join(" · ")}</span></span>
                {editable ? <Button variant="ghost" size="sm" onClick={() => setRemoving(c.id)}>Remove</Button> : null}
              </li>
            ))}
          </ul>
        )}
      </QueryState>
      {editable ? (
        <form className="grid grid-cols-1 items-end gap-3 sm:grid-cols-5" onSubmit={(e) => { e.preventDefault(); if (form.name.trim()) add.mutate(); }}>
          <Field id="c-name" label="Name"><Input id="c-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field id="c-email" label="Email"><Input id="c-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field id="c-phone" label="Phone"><Input id="c-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
          <Field id="c-role" label="Role"><Input id="c-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} /></Field>
          <Button type="submit" variant="secondary" loading={add.isPending}>Add contact</Button>
        </form>
      ) : null}
      <ConfirmDialog open={removing !== null} onOpenChange={(o) => !o && setRemoving(null)} title="Remove contact?" description="The contact is removed from this supplier." confirmLabel="Remove" pending={remove.isPending} onConfirm={() => removing && remove.mutate(removing)} />
    </Card>
  );
}

function MergeDialog({ open, onOpenChange, sourceId, sourceName }: { open: boolean; onOpenChange: (o: boolean) => void; sourceId: string; sourceName: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [target, setTarget] = useState("");
  const [confirm, setConfirm] = useState(false);
  const suppliers = useQuery({ queryKey: ["suppliers", "all"], queryFn: fetchAllSuppliers, enabled: open });
  const merge = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/suppliers/merge", { body: { source_id: sourceId, target_id: target } })),
    onSuccess: (t) => { toast.success(`Merged into ${t.name}`); void qc.invalidateQueries(); router.push(`/app/suppliers/${t.id}`); },
    onError: (e) => { setConfirm(false); toast.error(errorMessage(e)); },
  });
  return (
    <>
      <Dialog open={open && !confirm} onOpenChange={onOpenChange} title={`Merge ${sourceName}`} description="Codes, agreements, purchase lines, credits and products move to the supplier you choose. This is recorded in the audit log."
        footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!target} onClick={() => setConfirm(true)}>Continue</Button></>}>
        <Field id="merge-target" label="Merge into">
          <Select id="merge-target" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Choose a supplier…</option>
            {(suppliers.data ?? []).filter((s) => s.id !== sourceId).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
      </Dialog>
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title="Merge suppliers?" description={`${sourceName} will disappear and everything moves to the chosen supplier. This cannot be undone.`} confirmLabel="Merge" typeToConfirm={sourceName} pending={merge.isPending} onConfirm={() => merge.mutate()} />
    </>
  );
}
