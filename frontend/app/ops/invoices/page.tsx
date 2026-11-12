"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";
import { DataTable } from "@/components/data-table";
import { Button, Field, Input, Notice, PageHeader } from "@/components/ui/core";
import { DateText, Money, StatusBadge } from "@/components/ui/finance";
import { ConfirmDialog, Dialog, Drawer } from "@/components/ui/overlay";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export default function OpsInvoicesPage() {
  return <Suspense><Invoices /></Suspense>;
}

function Invoices() {
  const params = useSearchParams();
  const [open, setOpen] = useState<string | null>(params.get("open"));
  const query = useQuery({ queryKey: ["ops", "invoices"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/invoices")) });
  const tenants = useQuery({ queryKey: ["ops", "tenants"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/tenants")) });
  const names = new Map((tenants.data ?? []).map((t) => [t.id, t.name]));
  const settings = useQuery({ queryKey: ["ops", "billing-settings"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/billing-settings")) });
  return (
    <>
      <PageHeader title="Invoices" description="Sequential numbers are assigned when an invoice is issued. Issued invoices never change; correct them by voiding and reissuing. Drafts are created from an organization's page." />
      {settings.data && !settings.data.configured ? <div className="mb-4"><Notice tone="warning" title="Billing is not configured">Set seller details and payment instructions under Billing settings before issuing invoices.</Notice></div> : null}
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No invoices yet">Create a draft from an organization&rsquo;s page.</EmptyState>}>
        {(rows) => (
          <DataTable
            label="Invoices"
            rows={rows}
            rowKey={(r) => r.id}
            exportName="invoices"
            onRowClick={(r) => setOpen(r.id)}
            columns={[
              { id: "number", header: "Number", value: (r) => r.number ?? "", cell: (r) => <span className="font-mono">{r.number ?? "Draft"}</span> },
              { id: "org", header: "Organization", value: (r) => names.get(r.tenant_id) ?? "" },
              { id: "status", header: "Status", value: (r) => r.status, cell: (r) => <StatusBadge status={r.status} /> },
              { id: "issued", header: "Issued", value: (r) => r.issue_date ?? "", cell: (r) => <DateText value={r.issue_date} /> },
              { id: "due", header: "Due", value: (r) => r.due_date ?? "", cell: (r) => <DateText value={r.due_date} /> },
              { id: "total", header: "Total", value: (r) => r.total, numeric: true, align: "right", cell: (r) => <Money value={r.total} /> },
              { id: "paid", header: "Paid", value: (r) => r.paid_on ?? "", cell: (r) => <DateText value={r.paid_on} /> },
            ]}
          />
        )}
      </QueryState>
      <InvoiceDrawer id={open} onClose={() => setOpen(null)} orgName={open ? names.get((query.data ?? []).find((i) => i.id === open)?.tenant_id ?? "") : undefined} />
    </>
  );
}

function InvoiceDrawer({ id, onClose, orgName }: { id: string | null; onClose: () => void; orgName?: string }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["ops", "invoice", id], enabled: !!id, queryFn: async () => unwrap(await api.GET("/api/v1/ops/invoices/{invoice_id}", { params: { path: { invoice_id: id ?? "" } } })) });
  const [paying, setPaying] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const [issuing, setIssuing] = useState(false);
  const [paid, setPaid] = useState({ on: new Date().toISOString().slice(0, 10), ref: "" });
  const [reason, setReason] = useState("");
  const done = (msg: string) => async () => { toast.success(msg); setPaying(false); setVoiding(false); setIssuing(false); await qc.invalidateQueries({ queryKey: ["ops"] }); };
  const path = { params: { path: { invoice_id: id ?? "" } } };
  const issue = useMutation({ mutationFn: async () => unwrap(await api.POST("/api/v1/ops/invoices/{invoice_id}/issue", path)), onSuccess: done("Invoice issued and emailed"), onError: (e) => toast.error(errorMessage(e)) });
  const markPaid = useMutation({ mutationFn: async () => unwrap(await api.POST("/api/v1/ops/invoices/{invoice_id}/paid", { ...path, body: { paid_on: paid.on, reference: paid.ref } })), onSuccess: done("Marked paid"), onError: (e) => toast.error(errorMessage(e)) });
  const voidIt = useMutation({ mutationFn: async () => unwrap(await api.POST("/api/v1/ops/invoices/{invoice_id}/void", { ...path, body: { reason } })), onSuccess: done("Invoice voided"), onError: (e) => toast.error(errorMessage(e)) });
  const reissue = useMutation({ mutationFn: async () => unwrap(await api.POST("/api/v1/ops/invoices/{invoice_id}/reissue", path)), onSuccess: done("New draft created from the voided invoice"), onError: (e) => toast.error(errorMessage(e)) });
  const resend = useMutation({ mutationFn: async () => unwrap(await api.POST("/api/v1/ops/invoices/{invoice_id}/resend", path)), onSuccess: done("Invoice email queued"), onError: (e) => toast.error(errorMessage(e)) });
  return (
    <Drawer open={id !== null} onOpenChange={(o) => !o && onClose()} title="Invoice">
      <QueryState query={query}>
        {(inv) => (
          <div className="flex flex-col gap-4 text-sm">
            <div className="flex items-center justify-between"><span className="font-mono text-base">{inv.number ?? "Draft"}</span><StatusBadge status={inv.status} /></div>
            <dl className="grid grid-cols-2 gap-2">
              <div><dt className="text-xs text-muted">Organization</dt><dd>{orgName ?? String(inv.buyer.name ?? "")}</dd></div>
              <div><dt className="text-xs text-muted">Billing email</dt><dd>{String(inv.buyer.email ?? "—")}</dd></div>
              <div><dt className="text-xs text-muted">Issued</dt><dd><DateText value={inv.issue_date} /></dd></div>
              <div><dt className="text-xs text-muted">Due</dt><dd><DateText value={inv.due_date} /></dd></div>
              {inv.paid_on ? <div><dt className="text-xs text-muted">Paid</dt><dd><DateText value={inv.paid_on} /> · {inv.payment_reference}</dd></div> : null}
              {inv.emailed_at ? <div><dt className="text-xs text-muted">Last emailed</dt><dd>{formatDateTime(inv.emailed_at)}</dd></div> : null}
              {inv.void_reason ? <div className="col-span-2"><dt className="text-xs text-muted">Void reason</dt><dd>{inv.void_reason}</dd></div> : null}
            </dl>
            <table className="w-full" aria-label="Invoice lines">
              <thead><tr className="text-left text-xs text-muted uppercase"><th>Description</th><th className="text-right">Qty</th><th className="text-right">Unit</th><th className="text-right">Amount</th></tr></thead>
              <tbody>
                {inv.lines.map((l, i) => <tr key={i} className="border-t border-rule"><td className="py-1">{l.description}</td><td className="text-right">{l.quantity}</td><td className="text-right"><Money value={l.unit_price} /></td><td className="text-right"><Money value={l.amount} /></td></tr>)}
                <tr className="border-t border-ink font-semibold"><td colSpan={3}>Total</td><td className="text-right"><Money value={inv.total} /></td></tr>
              </tbody>
            </table>
            <div className="flex flex-wrap gap-2">
              {inv.status === "draft" ? <><Button onClick={() => setIssuing(true)}>Issue invoice</Button><Button variant="ghost" onClick={() => setVoiding(true)}>Delete draft</Button></> : null}
              {inv.status === "issued" ? <><Button onClick={() => setPaying(true)}>Mark paid</Button><Button variant="secondary" loading={resend.isPending} onClick={() => resend.mutate()}>Resend email</Button><Button variant="danger" onClick={() => setVoiding(true)}>Void</Button></> : null}
              {inv.status === "void" ? <Button variant="secondary" loading={reissue.isPending} onClick={() => reissue.mutate()}>Reissue as new draft</Button> : null}
              {inv.status !== "draft" ? <a className="inline-flex h-9 items-center text-brand underline" href={`/api/v1/ops/invoices/${inv.id}/pdf`}>Download PDF</a> : null}
            </div>
            <ConfirmDialog open={issuing} onOpenChange={setIssuing} title="Issue this invoice?" description="It gets the next sequential number, becomes immutable and is emailed to the billing contact." confirmLabel="Issue" pending={issue.isPending} onConfirm={() => issue.mutate()} />
            <Dialog open={paying} onOpenChange={setPaying} title="Record payment" description="Payments are recorded manually from your bank statement." footer={<><Button variant="secondary" onClick={() => setPaying(false)}>Cancel</Button><Button disabled={!paid.ref.trim()} loading={markPaid.isPending} onClick={() => markPaid.mutate()}>Mark paid</Button></>}>
              <div className="flex flex-col gap-3">
                <Field id="paid-on" label="Paid on"><Input id="paid-on" type="date" value={paid.on} onChange={(e) => setPaid({ ...paid, on: e.target.value })} /></Field>
                <Field id="paid-ref" label="Payment reference" required><Input id="paid-ref" value={paid.ref} maxLength={200} onChange={(e) => setPaid({ ...paid, ref: e.target.value })} /></Field>
              </div>
            </Dialog>
            <Dialog open={voiding} onOpenChange={setVoiding} title={inv.status === "draft" ? "Delete this draft?" : "Void this invoice?"} description={inv.status === "draft" ? "The draft is removed." : "The number stays used; the invoice is kept and marked void. Reissue to correct it."} footer={<><Button variant="secondary" onClick={() => setVoiding(false)}>Cancel</Button><Button variant="danger" disabled={reason.trim().length < 3} loading={voidIt.isPending} onClick={() => voidIt.mutate()}>{inv.status === "draft" ? "Delete" : "Void"}</Button></>}>
              <Field id="void-reason" label="Reason" required><Input id="void-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} /></Field>
            </Dialog>
          </div>
        )}
      </QueryState>
    </Drawer>
  );
}
