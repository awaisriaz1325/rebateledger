"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { ExplainDrawer } from "@/components/explain-drawer";
import { Button, Card, Field, Input, Notice, PageHeader, Select, Textarea } from "@/components/ui/core";
import { DateText, Money, StatusBadge, statusLabel } from "@/components/ui/finance";
import { ConfirmDialog, Dialog } from "@/components/ui/overlay";
import { QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap, uploadForm } from "@/lib/api";
import { isConflict, useVersioned } from "@/lib/etag";
import { formatDateTime } from "@/lib/format";
import { useNames } from "@/lib/queries";
import { can, useSession } from "@/lib/session";
import type { ClaimDetail } from "@/lib/types";
import type { components } from "@/generated/api";

type Patch = components["schemas"]["ClaimPatch"];
type ClaimStatus = components["schemas"]["TransitionIn"]["to"];
const MONEY_RE = /^\d{1,14}(\.\d{1,4})?$/;
/** A short payment's variance is negative (received − expected); the amount to recover is its magnitude. String-only, no arithmetic. */
function shortfall(variance: string): string {
  return variance.startsWith("-") ? variance.slice(1) : "0";
}
const ACTION_LABEL: Record<string, string> = {
  draft: "Back to draft",
  ready: "Mark ready",
  submitted: "Mark submitted to supplier",
  acknowledged: "Supplier acknowledged",
  resolved_recovered: "Resolve: fully recovered",
  resolved_partial: "Resolve: partly recovered",
  rejected: "Supplier rejected",
  written_off: "Write off…",
};

export default function ClaimPage() {
  const { id } = useParams<{ id: string }>();
  const query = useVersioned<ClaimDetail>(["claim", id], () => api.GET("/api/v1/claims/{claim_id}", { params: { path: { claim_id: id } } }));
  return <QueryState query={query}>{(v) => <ClaimView claim={v.data} etag={v.etag} />}</QueryState>;
}

function ClaimView({ claim, etag }: { claim: ClaimDetail; etag: string }) {
  const session = useSession();
  const edit = can(session, "edit_claims");
  const names = useNames();
  const closed = claim.status === "resolved_recovered" || claim.status === "written_off";
  const [explain, setExplain] = useState<string | null>(null);
  return (
    <>
      <PageHeader title={`Claim #${claim.number}: ${claim.title}`} description={<>{names.data?.supplier.get(claim.supplier_id) ?? "Supplier"} · opened {formatDateTime(claim.created_at)}</>}>
        <div className="mt-2 flex gap-2"><StatusBadge status={claim.status} />{claim.pending_write_off ? <span className="text-xs text-warning">Write-off awaiting approval</span> : null}</div>
      </PageHeader>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
        <div className="flex flex-col gap-6">
          <Card>
            <dl className="grid grid-cols-3 gap-4 text-sm">
              <div><dt className="text-xs text-muted">Identified</dt><dd className="text-lg font-semibold"><Money value={claim.identified_amount} /></dd></div>
              <div><dt className="text-xs text-muted">Claimed</dt><dd className="text-lg font-semibold"><Money value={claim.claimed_amount} /></dd>{claim.claimed_amount_reason ? <dd className="text-xs text-muted">{claim.claimed_amount_reason}</dd> : null}</div>
              <div><dt className="text-xs text-muted">Recovered</dt><dd className="text-lg font-semibold"><Money value={claim.recovered_amount} /></dd></div>
            </dl>
          </Card>
          {edit && !closed ? <Lifecycle claim={claim} /> : null}
          <Card title="Periods in this claim">
            <p className="mb-2 text-xs text-muted">Amounts as they were when the claim was opened.</p>
            <table className="w-full text-sm" aria-label="Claim periods">
              <thead><tr className="text-left text-xs text-muted uppercase"><th className="py-1">Agreement</th><th>Period</th><th className="text-right">Expected</th><th className="text-right">Received</th><th className="text-right">Variance</th><th /></tr></thead>
              <tbody>
                {claim.items.map((i) => (
                  <tr key={i.id} className="border-t border-rule">
                    <td className="py-1.5"><Link href={`/app/agreements/${i.agreement_id}`} className="hover:underline">{names.data?.agreement.get(i.agreement_id) ?? "Agreement"}</Link></td>
                    <td>{i.period_start} – {i.period_end}</td>
                    <td className="text-right"><Money value={i.expected} /></td>
                    <td className="text-right"><Money value={i.received_at_creation} /></td>
                    <td className="text-right"><Money value={i.variance_at_creation} emphasize /></td>
                    <td className="text-right"><Button size="sm" variant="ghost" onClick={() => setExplain(i.result_id)}>Explain</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <Recoveries claim={claim} edit={edit && !closed} />
          <Activity claim={claim} edit={edit} />
        </div>
        <div className="flex flex-col gap-6">
          <Details claim={claim} etag={etag} edit={edit && !closed} />
          <Attachments claim={claim} edit={edit} />
        </div>
      </div>
      <ExplainDrawer resultId={explain} open={explain !== null} onOpenChange={(o) => !o && setExplain(null)} />
    </>
  );
}

function useRefresh(id: string) {
  const qc = useQueryClient();
  return () => Promise.all([qc.invalidateQueries({ queryKey: ["claim", id] }), qc.invalidateQueries({ queryKey: ["claims"] }), qc.invalidateQueries({ queryKey: ["discrepancies"] }), qc.invalidateQueries({ queryKey: ["reconciliation"] })]);
}

function Lifecycle({ claim }: { claim: ClaimDetail }) {
  const session = useSession();
  const refresh = useRefresh(claim.id);
  const [to, setTo] = useState<ClaimStatus | null>(null);
  const [note, setNote] = useState("");
  const move = useMutation({
    mutationFn: async (target: ClaimStatus) => unwrap(await api.POST("/api/v1/claims/{claim_id}/transition", { params: { path: { claim_id: claim.id } }, body: { to: target, note } })),
    onSuccess: async (c) => {
      setTo(null);
      setNote("");
      toast.success(c.pending_write_off ? "Write-off sent for approval" : `Claim is now ${statusLabel(c.status).toLowerCase()}`);
      await refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const allowed = claim.allowed_transitions.filter((t) => t !== "written_off" || can(session, "write_off_claims")) as ClaimStatus[];
  if (claim.pending_write_off) return <Notice tone="warning" title="Write-off awaiting approval">Someone else with approval rights must approve it on the Approvals page.</Notice>;
  if (!allowed.length) return null;
  const writingOff = to === "written_off";
  return (
    <Card title="Next step">
      <div className="flex flex-wrap gap-2">
        {allowed.map((t) => <Button key={t} size="sm" variant={t === "written_off" ? "danger" : t === "draft" ? "ghost" : "secondary"} onClick={() => setTo(t)}>{ACTION_LABEL[t] ?? statusLabel(t)}</Button>)}
      </div>
      <Dialog
        open={to !== null}
        onOpenChange={(o) => !o && setTo(null)}
        title={to ? ACTION_LABEL[to]?.replace("…", "") ?? statusLabel(to) : ""}
        description={writingOff ? "Writing off closes the claim without recovering the rest. A reason is required and is kept in the audit log." : "Add a note for the claim history (optional)."}
        footer={<><Button variant="secondary" onClick={() => setTo(null)}>Cancel</Button><Button variant={writingOff ? "danger" : "primary"} disabled={writingOff && note.trim().length < 3} loading={move.isPending} onClick={() => to && move.mutate(to)}>Confirm</Button></>}
      >
        <Field id="tr-note" label={writingOff ? "Reason" : "Note"} required={writingOff}><Textarea id="tr-note" rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </Dialog>
    </Card>
  );
}

function Details({ claim, etag, edit }: { claim: ClaimDetail; etag: string; edit: boolean }) {
  const refresh = useRefresh(claim.id);
  const members = useQuery({ queryKey: ["members"], queryFn: async () => unwrap(await api.GET("/api/v1/org/members")) });
  const people = new Map((members.data ?? []).map((m) => [m.user_id, m.name]));
  const [editing, setEditing] = useState(false);
  const [f, setF] = useState({ assignee_id: claim.assignee_id ?? "", due_date: claim.due_date ?? "", follow_up_date: claim.follow_up_date ?? "", channel: claim.channel, claimed_amount: claim.claimed_amount, claimed_amount_reason: claim.claimed_amount_reason });
  const [conflict, setConflict] = useState(false);
  const amountChanged = f.claimed_amount !== claim.claimed_amount;
  const save = useMutation({
    mutationFn: async () => {
      const body: Patch = { assignee_id: f.assignee_id || null, due_date: f.due_date || null, follow_up_date: f.follow_up_date || null, channel: f.channel as Patch["channel"] };
      if (amountChanged) { body.claimed_amount = f.claimed_amount; body.claimed_amount_reason = f.claimed_amount_reason; }
      return unwrap(await api.PATCH("/api/v1/claims/{claim_id}", { params: { path: { claim_id: claim.id } }, body, headers: { "If-Match": etag } }));
    },
    onSuccess: async () => { setEditing(false); toast.success("Claim updated"); await refresh(); },
    onError: (e) => { if (isConflict(e)) setConflict(true); else toast.error(errorMessage(e)); },
  });
  return (
    <Card title="Details" actions={edit && !editing ? <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>Edit</Button> : null}>
      {conflict ? <div className="mb-3"><Notice tone="warning" title="Someone else changed this claim" action={<Button size="sm" variant="secondary" onClick={() => { setConflict(false); setEditing(false); void refresh(); }}>Reload</Button>}>Reload to see their changes, then edit again.</Notice></div> : null}
      {editing ? (
        <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field id="cd-assignee" label="Assignee">
            <Select id="cd-assignee" value={f.assignee_id} onChange={(e) => setF({ ...f, assignee_id: e.target.value })}>
              <option value="">Unassigned</option>
              {(members.data ?? []).filter((m) => m.status === "active").map((m) => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
            </Select>
          </Field>
          <Field id="cd-due" label="Due date"><Input id="cd-due" type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
          <Field id="cd-follow" label="Follow up on"><Input id="cd-follow" type="date" value={f.follow_up_date} onChange={(e) => setF({ ...f, follow_up_date: e.target.value })} /></Field>
          <Field id="cd-channel" label="Channel">
            <Select id="cd-channel" value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })}>
              <option value="email">Email</option><option value="portal">Supplier portal</option><option value="phone">Phone</option><option value="other">Other</option>
            </Select>
          </Field>
          <Field id="cd-amount" label="Claimed amount ($)" hint="Defaults to the identified variance." error={MONEY_RE.test(f.claimed_amount) ? undefined : "Use digits, e.g. 1250.00 (up to 4 decimals)"}><Input id="cd-amount" inputMode="decimal" className="text-right" value={f.claimed_amount} onChange={(e) => setF({ ...f, claimed_amount: e.target.value.trim() })} /></Field>
          {amountChanged ? <Field id="cd-reason" label="Why the claimed amount differs" required><Input id="cd-reason" maxLength={500} value={f.claimed_amount_reason} onChange={(e) => setF({ ...f, claimed_amount_reason: e.target.value })} /></Field> : null}
          <div className="flex gap-2"><Button type="submit" size="sm" loading={save.isPending} disabled={!MONEY_RE.test(f.claimed_amount) || (amountChanged && !f.claimed_amount_reason.trim())}>Save</Button><Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button></div>
        </form>
      ) : (
        <dl className="flex flex-col gap-2 text-sm">
          <div><dt className="text-xs text-muted">Assignee</dt><dd>{claim.assignee_id ? people.get(claim.assignee_id) ?? "—" : "Unassigned"}</dd></div>
          <div><dt className="text-xs text-muted">Due</dt><dd><DateText value={claim.due_date} /></dd></div>
          <div><dt className="text-xs text-muted">Follow up on</dt><dd><DateText value={claim.follow_up_date} /></dd></div>
          <div><dt className="text-xs text-muted">Channel</dt><dd className="capitalize">{claim.channel}</dd></div>
          <div><dt className="text-xs text-muted">Submitted</dt><dd>{claim.submitted_at ? formatDateTime(claim.submitted_at) : "—"}</dd></div>
          {claim.resolved_at ? <div><dt className="text-xs text-muted">Closed</dt><dd>{formatDateTime(claim.resolved_at)}</dd></div> : null}
          {claim.write_off_reason ? <div><dt className="text-xs text-muted">Write-off reason</dt><dd>{claim.write_off_reason}</dd></div> : null}
        </dl>
      )}
    </Card>
  );
}

function Recoveries({ claim, edit }: { claim: ClaimDetail; edit: boolean }) {
  const refresh = useRefresh(claim.id);
  const [linking, setLinking] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const remove = useMutation({
    mutationFn: async (rid: string) => unwrap(await api.DELETE("/api/v1/claims/{claim_id}/recoveries/{recovery_id}", { params: { path: { claim_id: claim.id, recovery_id: rid } } })),
    onSuccess: async () => { setRemoving(null); toast.success("Recovery unlinked"); await refresh(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Recovered money" actions={edit ? <Button size="sm" variant="secondary" onClick={() => setLinking(true)}>Link a credit</Button> : null}>
      <p className="mb-3 text-xs text-muted">Recoveries are recorded only by linking the supplier&rsquo;s actual credit. Nothing is assumed.</p>
      {claim.recoveries.length === 0 ? <p className="text-sm text-muted">No credits linked yet.</p> : (
        <ul className="divide-y divide-rule rounded-md border border-rule text-sm">
          {claim.recoveries.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-2 px-3 py-2">
              <span>Credit linked {formatDateTime(r.linked_at)}</span>
              <span className="flex items-center gap-2"><Money value={r.amount} />{edit ? <Button size="sm" variant="ghost" onClick={() => setRemoving(r.id)}>Unlink</Button> : null}</span>
            </li>
          ))}
        </ul>
      )}
      {linking ? <LinkRecovery claim={claim} onClose={() => setLinking(false)} /> : null}
      <ConfirmDialog open={removing !== null} onOpenChange={(o) => !o && setRemoving(null)} title="Unlink this recovery?" description="The credit's allocations to this claim's periods are reversed. The credit itself is kept." confirmLabel="Unlink" pending={remove.isPending} onConfirm={() => removing && remove.mutate(removing)} />
    </Card>
  );
}

function LinkRecovery({ claim, onClose }: { claim: ClaimDetail; onClose: () => void }) {
  const refresh = useRefresh(claim.id);
  const names = useNames();
  const credits = useQuery({ queryKey: ["credits", "supplier", claim.supplier_id], queryFn: async () => unwrap(await api.GET("/api/v1/credits", { params: { query: { supplier_id: claim.supplier_id, limit: 200 } } })).items });
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [creditId, setCreditId] = useState("");
  const [nc, setNc] = useState({ reference: "", credit_date: "", amount: "" });
  const [amounts, setAmounts] = useState<Record<string, string>>(() => Object.fromEntries(claim.items.map((i) => [i.id, shortfall(i.variance_at_creation)])));
  const parts = Object.entries(amounts).filter(([, a]) => a !== "" && a !== "0" && a !== "0.00");
  const invalid = parts.length === 0 || parts.some(([, a]) => !MONEY_RE.test(a)) || (mode === "existing" ? !creditId : !nc.reference.trim() || !nc.credit_date || !MONEY_RE.test(nc.amount));
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/claims/{claim_id}/recoveries", {
          params: { path: { claim_id: claim.id } },
          body: { credit_id: mode === "existing" ? creditId : null, new_credit: mode === "new" ? { ...nc, reference: nc.reference.trim() } : null, allocations: parts.map(([item_id, amount]) => ({ item_id, amount })) },
        }),
      ),
    onSuccess: async () => { toast.success("Recovery linked"); await refresh(); onClose(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog open wide onOpenChange={(o) => !o && onClose()} title="Link a recovering credit" description="Choose the supplier credit that paid this claim and how much of it goes to each period." footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={() => save.mutate()} disabled={invalid} loading={save.isPending}>Link credit</Button></>}>
      <fieldset className="mb-4 flex gap-4 text-sm">
        <legend className="sr-only">Credit source</legend>
        <label className="flex items-center gap-2"><input type="radio" name="src" checked={mode === "existing"} onChange={() => setMode("existing")} /> A credit already imported</label>
        <label className="flex items-center gap-2"><input type="radio" name="src" checked={mode === "new"} onChange={() => setMode("new")} /> Enter a new credit</label>
      </fieldset>
      {mode === "existing" ? (
        <Field id="lr-credit" label="Credit">
          <Select id="lr-credit" value={creditId} onChange={(e) => setCreditId(e.target.value)}>
            <option value="">Choose…</option>
            {(credits.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.credit_reference} · {c.credit_date} · ${c.amount}</option>)}
          </Select>
        </Field>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field id="lr-ref" label="Credit memo number" required><Input id="lr-ref" maxLength={100} value={nc.reference} onChange={(e) => setNc({ ...nc, reference: e.target.value })} /></Field>
          <Field id="lr-date" label="Date" required><Input id="lr-date" type="date" value={nc.credit_date} onChange={(e) => setNc({ ...nc, credit_date: e.target.value })} /></Field>
          <Field id="lr-amt" label="Amount ($)" required><Input id="lr-amt" inputMode="decimal" className="text-right" value={nc.amount} onChange={(e) => setNc({ ...nc, amount: e.target.value.trim() })} /></Field>
        </div>
      )}
      <h3 className="mt-5 mb-2 text-sm font-semibold">Amount for each period</h3>
      <ul className="flex flex-col gap-2">
        {claim.items.map((i) => (
          <li key={i.id} className="grid grid-cols-[1fr_160px] items-center gap-3 text-sm">
            <label htmlFor={`lr-i-${i.id}`}>{names.data?.agreement.get(i.agreement_id) ?? "Agreement"} · {i.period_start} – {i.period_end} <span className="text-xs text-muted">(variance <Money value={i.variance_at_creation} />)</span></label>
            <Input id={`lr-i-${i.id}`} inputMode="decimal" className="text-right" value={amounts[i.id] ?? ""} onChange={(e) => setAmounts({ ...amounts, [i.id]: e.target.value.trim() })} />
          </li>
        ))}
      </ul>
    </Dialog>
  );
}

function Activity({ claim, edit }: { claim: ClaimDetail; edit: boolean }) {
  const refresh = useRefresh(claim.id);
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/claims/{claim_id}/notes", { params: { path: { claim_id: claim.id } }, body: { text } })),
    onSuccess: async () => { setText(""); await refresh(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="History">
      {edit ? (
        <form className="mb-4 flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) add.mutate(); }}>
          <label htmlFor="note" className="sr-only">Add a note</label>
          <Textarea id="note" rows={2} maxLength={5000} placeholder="Add a note (e.g. who you spoke to at the supplier)" value={text} onChange={(e) => setText(e.target.value)} />
          <div><Button type="submit" size="sm" variant="secondary" loading={add.isPending} disabled={!text.trim()}>Add note</Button></div>
        </form>
      ) : null}
      <ol className="flex flex-col gap-3 text-sm">
        {[...claim.events].reverse().map((e) => (
          <li key={e.id} className="border-l-2 border-rule pl-3">
            <p className="text-xs text-muted">{formatDateTime(e.occurred_at)} · {e.actor_label}</p>
            <p>{e.from_status && e.to_status ? <>Moved from <strong>{statusLabel(e.from_status)}</strong> to <strong>{statusLabel(e.to_status)}</strong>. </> : null}<span className="whitespace-pre-wrap">{e.text}</span></p>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Attachments({ claim, edit }: { claim: ClaimDetail; edit: boolean }) {
  const refresh = useRefresh(claim.id);
  const [busy, setBusy] = useState(false);
  async function upload(file: File) {
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      await uploadForm(`/api/v1/claims/${claim.id}/attachments`, form);
      toast.success("Attachment added");
      await refresh();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title="Attachments">
      {claim.attachments.length === 0 ? <p className="text-sm text-muted">No files yet.</p> : (
        <ul className="flex flex-col gap-1 text-sm">
          {claim.attachments.map((a) => <li key={a.id}><a className="text-brand underline" href={`/api/v1/claims/attachments/${a.id}/download`}>{a.filename}</a> <span className="text-xs text-muted">({Math.ceil(a.size_bytes / 1024)} KB)</span></li>)}
        </ul>
      )}
      {edit ? (
        <div className="mt-3">
          <label htmlFor="att" className="text-xs text-muted">Add a PDF, Word, Excel, PNG or JPEG file (max 20 MB)</label>
          <input id="att" type="file" accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg" disabled={busy} className="mt-1 block text-sm" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
        </div>
      ) : null}
    </Card>
  );
}
