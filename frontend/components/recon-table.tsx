"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { DataTable } from "@/components/data-table";
import { ExplainDrawer } from "@/components/explain-drawer";
import { Button, Field, Input, Select, Textarea } from "@/components/ui/core";
import { DateText, Money, StatusBadge } from "@/components/ui/finance";
import { Dialog } from "@/components/ui/overlay";
import { api, errorMessage, idempotencyKey, unwrap } from "@/lib/api";
import { can, useSession } from "@/lib/session";
import type { ReconRow } from "@/lib/types";

export const RECON_STATUSES = ["MATCHED", "NOT_EARNED", "PENDING", "SHORT_PAID", "MISSING", "OVERPAID", "NEEDS_REVIEW"] as const;
const CLAIMABLE = new Set(["SHORT_PAID", "MISSING"]);

/** Reconciliation rows with Explain, claim links and multi-select to open a claim. */
export function ReconTable({ rows, label, exportName }: { rows: ReconRow[]; label: string; exportName: string }) {
  const session = useSession();
  const canClaim = can(session, "edit_claims");
  const [explain, setExplain] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState(false);
  const chosen = rows.filter((r) => selected.has(r.result_id));
  const suppliers = new Set(chosen.map((r) => r.supplier_id));
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  return (
    <>
      <DataTable
        label={label}
        rows={rows}
        rowKey={(r) => r.result_id}
        exportName={exportName}
        onRowClick={(r) => setExplain(r.result_id)}
        toolbar={canClaim ? (
          <div className="flex items-center gap-2 text-sm">
            {chosen.length ? <span className="text-muted">{chosen.length} selected</span> : null}
            <Button size="sm" disabled={chosen.length === 0 || suppliers.size > 1} title={suppliers.size > 1 ? "A claim covers one supplier" : undefined} onClick={() => setCreating(true)}>Create claim</Button>
          </div>
        ) : undefined}
        columns={[
          ...(canClaim ? [{
            id: "select", header: "Select", value: () => "",
            cell: (r: ReconRow) => CLAIMABLE.has(r.status) && !r.claim_id ? (
              <input type="checkbox" aria-label={`Select ${r.agreement_name} ${r.period_label}`} checked={selected.has(r.result_id)} onClick={(e) => e.stopPropagation()} onChange={() => toggle(r.result_id)} />
            ) : null,
          }] : []),
          { id: "supplier", header: "Supplier", value: (r) => r.supplier_name, cell: (r) => <Link href={`/app/suppliers/${r.supplier_id}`} onClick={(e) => e.stopPropagation()} className="hover:underline">{r.supplier_name}</Link> },
          { id: "agreement", header: "Agreement", value: (r) => r.agreement_name, cell: (r) => <Link href={`/app/agreements/${r.agreement_id}`} onClick={(e) => e.stopPropagation()} className="font-medium hover:underline">{r.agreement_name}</Link> },
          { id: "period", header: "Period", value: (r) => r.period_label },
          { id: "expected", header: "Expected", value: (r) => r.expected ?? "", numeric: true, align: "right", cell: (r) => (r.expected == null ? <span className="text-muted">—</span> : <Money value={r.expected} />) },
          { id: "received", header: "Received", value: (r) => r.received, numeric: true, align: "right", cell: (r) => <Money value={r.received} /> },
          { id: "variance", header: "Variance", value: (r) => r.variance ?? "", numeric: true, align: "right", cell: (r) => (r.variance == null ? <span className="text-muted">—</span> : <Money value={r.variance} emphasize />) },
          { id: "status", header: "Status", value: (r) => r.status, cell: (r) => <span className="flex flex-wrap gap-1"><StatusBadge status={r.status} />{r.stale ? <StatusBadge status="STALE" /> : null}</span> },
          { id: "due", header: "Due", value: (r) => r.due_date, cell: (r) => <DateText value={r.due_date} /> },
          { id: "age", header: "Days past due", value: (r) => r.days_past_due, align: "right", cell: (r) => (r.days_past_due > 0 ? r.days_past_due : "") },
          { id: "claim", header: "Claim", value: (r) => r.claim_number ?? "", cell: (r) => (r.claim_id ? <Link href={`/app/claims/${r.claim_id}`} onClick={(e) => e.stopPropagation()} className="text-brand hover:underline">#{r.claim_number}</Link> : null) },
          { id: "version", header: "Version", value: (r) => r.version_no, hidden: true },
          { id: "run", header: "Run", value: (r) => r.run_number, hidden: true },
          { id: "flags", header: "Flags", value: (r) => [...r.flags, ...r.engine_statuses].join(" "), hidden: true },
        ]}
      />
      <ExplainDrawer resultId={explain} open={explain !== null} onOpenChange={(o) => !o && setExplain(null)} />
      {creating ? <CreateClaim rows={chosen} onClose={() => { setCreating(false); }} onCreated={() => setSelected(new Set())} /> : null}
    </>
  );
}

function CreateClaim({ rows, onClose, onCreated }: { rows: ReconRow[]; onClose: () => void; onCreated: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["members"], queryFn: async () => unwrap(await api.GET("/api/v1/org/members")) });
  const first = rows[0];
  const [title, setTitle] = useState(first ? `${first.supplier_name} — ${rows.length === 1 ? `${first.agreement_name} ${first.period_label}` : `${rows.length} periods`}` : "");
  const [assignee, setAssignee] = useState("");
  const [due, setDue] = useState("");
  const [notes, setNotes] = useState("");
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/claims", {
          body: { result_ids: rows.map((r) => r.result_id), title: title.trim() || null, assignee_id: assignee || null, due_date: due || null, notes, channel: "email", claimed_amount_reason: "" },
          headers: { "Idempotency-Key": idempotencyKey() },
        }),
      ),
    onSuccess: async (claim) => {
      onCreated();
      await qc.invalidateQueries({ queryKey: ["reconciliation"] });
      await qc.invalidateQueries({ queryKey: ["discrepancies"] });
      toast.success(`Claim #${claim.number} created`);
      router.push(`/app/claims/${claim.id}`);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Create a claim"
      description="The claim records the expected, received and variance amounts as they are now. Later runs do not change it."
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={() => create.mutate()} loading={create.isPending}>Create claim</Button></>}
    >
      <ul className="mb-4 max-h-40 overflow-y-auto rounded-md border border-rule text-sm">
        {rows.map((r) => (
          <li key={r.result_id} className="flex justify-between gap-3 border-b border-rule px-3 py-1.5 last:border-0">
            <span>{r.agreement_name} · {r.period_label}</span>
            <Money value={r.variance} />
          </li>
        ))}
      </ul>
      <div className="flex flex-col gap-3">
        <Field id="claim-title" label="Title"><Input id="claim-title" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} /></Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field id="claim-assignee" label="Assignee">
            <Select id="claim-assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              <option value="">Unassigned</option>
              {(members.data ?? []).filter((m) => m.status === "active").map((m) => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
            </Select>
          </Field>
          <Field id="claim-due" label="Due date"><Input id="claim-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
        </div>
        <Field id="claim-notes" label="Notes"><Textarea id="claim-notes" rows={3} maxLength={10000} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
    </Dialog>
  );
}
