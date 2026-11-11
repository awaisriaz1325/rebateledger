"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { DataTable } from "@/components/data-table";
import { Button, Field, Input, Notice, PageHeader, Select, Textarea } from "@/components/ui/core";
import { DateText, Money } from "@/components/ui/finance";
import { ConfirmDialog, Dialog, Drawer, Tabs } from "@/components/ui/overlay";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useNames } from "@/lib/queries";
import { can, useSession } from "@/lib/session";
import type { Credit, Unmatched } from "@/lib/types";

/** Decimal money as typed by a person: digits with up to two decimals (backend re-validates). */
const MONEY_RE = /^-?\d{1,14}(\.\d{1,4})?$/;

export default function CreditsPage() {
  const session = useSession();
  const [entering, setEntering] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const allocate = can(session, "run_reconciliation");
  return (
    <>
      <PageHeader
        title="Credits"
        description="Rebate credits received from suppliers. Allocate each to the agreement period it pays so variances are right."
        actions={allocate ? <Button onClick={() => setEntering(true)}>Enter a credit</Button> : null}
      />
      <Tabs
        label="Credit views"
        tabs={[
          { value: "unmatched", label: "Needs allocation", content: <UnmatchedList allocate={allocate} onOpen={setOpen} /> },
          { value: "all", label: "All credits", content: <AllCredits onOpen={setOpen} /> },
        ]}
      />
      {entering ? <ManualCredit onClose={() => setEntering(false)} /> : null}
      <CreditDrawer creditId={open} onClose={() => setOpen(null)} allocate={allocate} />
    </>
  );
}

function UnmatchedList({ allocate, onOpen }: { allocate: boolean; onOpen: (id: string) => void }) {
  const names = useNames();
  const query = useQuery({ queryKey: ["credits", "unmatched"], queryFn: async () => unwrap(await api.GET("/api/v1/credits/unmatched")) });
  const [target, setTarget] = useState<Unmatched | null>(null);
  return (
    <>
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="Every credit is allocated">New credits from imports appear here when they cannot be matched automatically.</EmptyState>}>
        {(rows) => (
          <ul className="flex flex-col gap-3">
            {rows.map((c) => (
              <li key={c.id} className="rounded-lg border border-rule bg-surface p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <button type="button" className="font-medium hover:underline" onClick={() => onOpen(c.id)}>{names.data?.supplier.get(c.supplier_id) ?? "Supplier"} · {c.credit_reference}</button>
                    <p className="text-xs text-muted"><DateText value={c.credit_date} />{c.memo ? ` · ${c.memo}` : ""}{c.agreement_reference ? ` · ref ${c.agreement_reference}` : ""}</p>
                    {c.possible_duplicate ? <p className="mt-1 text-xs text-warning">Possible duplicate of another credit — check before allocating.</p> : null}
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-muted">Unallocated</p>
                    <p className="text-lg font-semibold"><Money value={c.unallocated} /></p>
                    <p className="text-xs text-muted">of <Money value={c.amount} /></p>
                  </div>
                </div>
                {c.suggestions.length ? (
                  <div className="mt-3 border-t border-rule pt-3">
                    <p className="text-xs font-medium text-muted uppercase">Suggestions</p>
                    <ul className="mt-1 text-sm">
                      {c.suggestions.map((s) => (
                        <li key={`${s.agreement_id}-${s.period_start}`} className="py-0.5">
                          <strong>{names.data?.agreement.get(s.agreement_id) ?? "Agreement"}</strong> {s.period_start} – {s.period_end}: <span className="text-muted">{s.explanation}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {allocate ? <Button size="sm" className="mt-3" onClick={() => setTarget(c)}>Allocate…</Button> : null}
              </li>
            ))}
          </ul>
        )}
      </QueryState>
      {target ? <AllocateDialog credit={target} onClose={() => setTarget(null)} /> : null}
    </>
  );
}

function AllCredits({ onOpen }: { onOpen: (id: string) => void }) {
  const names = useNames();
  const query = useInfiniteQuery({
    queryKey: ["credits", "all"],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => unwrap(await api.GET("/api/v1/credits", { params: { query: { cursor: pageParam, limit: 200 } } })),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const flat = { ...query, data: query.data?.pages.flatMap((p) => p.items) };
  return (
    <>
      <QueryState query={flat} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No credits yet">Import supplier credit memos, or enter one by hand.</EmptyState>}>
        {(rows: Credit[]) => (
          <DataTable
            label="Credits"
            rows={rows}
            rowKey={(r) => r.id}
            exportName="credits"
            onRowClick={(r) => onOpen(r.id)}
            columns={[
              { id: "supplier", header: "Supplier", value: (r) => names.data?.supplier.get(r.supplier_id) ?? "" },
              { id: "ref", header: "Reference", value: (r) => r.credit_reference, cell: (r) => <span className="font-mono text-xs">{r.credit_reference}</span> },
              { id: "date", header: "Date", value: (r) => r.credit_date, cell: (r) => <DateText value={r.credit_date} /> },
              { id: "amount", header: "Amount", value: (r) => r.amount, numeric: true, align: "right", cell: (r) => <Money value={r.amount} /> },
              { id: "period", header: "Period on memo", value: (r) => r.period_label ?? "" },
              { id: "memo", header: "Memo", value: (r) => r.memo, cell: (r) => <span className="line-clamp-1 max-w-xs text-xs text-muted">{r.memo}</span> },
              { id: "source", header: "Source", value: (r) => (r.batch_id ? "Import" : "Manual") },
            ]}
          />
        )}
      </QueryState>
      {query.hasNextPage ? <Button variant="secondary" className="mt-3" onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage}>Load more</Button> : null}
    </>
  );
}

interface Part { agreement_id: string; period_start: string; period_end: string; amount: string }

function AllocateDialog({ credit, onClose }: { credit: Unmatched; onClose: () => void }) {
  const qc = useQueryClient();
  const names = useNames();
  const agreements = (names.data?.agreements ?? []).filter((a) => a.supplier_id === credit.supplier_id);
  const first = credit.suggestions[0];
  const [parts, setParts] = useState<Part[]>([{ agreement_id: first?.agreement_id ?? "", period_start: first?.period_start ?? "", period_end: first?.period_end ?? "", amount: credit.unallocated }]);
  const set = (i: number, patch: Partial<Part>) => setParts(parts.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  const invalid = parts.some((p) => !p.agreement_id || !p.period_start || !p.period_end || p.period_end < p.period_start || !MONEY_RE.test(p.amount));
  const save = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/credits/{credit_id}/allocations", { params: { path: { credit_id: credit.id } }, body: { parts } })),
    onSuccess: async () => {
      toast.success("Credit allocated");
      await Promise.all([qc.invalidateQueries({ queryKey: ["credits"] }), qc.invalidateQueries({ queryKey: ["reconciliation"] }), qc.invalidateQueries({ queryKey: ["discrepancies"] })]);
      onClose();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog
      open
      wide
      onOpenChange={(o) => !o && onClose()}
      title={`Allocate ${credit.credit_reference}`}
      description={<>Unallocated: <Money value={credit.unallocated} />. Split it across periods if the supplier paid several at once. The total may not exceed the unallocated amount.</>}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={() => save.mutate()} disabled={invalid} loading={save.isPending}>Allocate</Button></>}
    >
      {credit.suggestions.length > 1 ? (
        <div className="mb-3 flex flex-wrap gap-2">
          {credit.suggestions.map((s) => (
            <Button key={`${s.agreement_id}-${s.period_start}`} size="sm" variant="secondary" onClick={() => setParts([...parts.filter((p) => p.agreement_id), { agreement_id: s.agreement_id, period_start: s.period_start, period_end: s.period_end, amount: "" }])}>
              + {names.data?.agreement.get(s.agreement_id) ?? "Agreement"} {s.period_start}
            </Button>
          ))}
        </div>
      ) : null}
      <div className="flex flex-col gap-3">
        {parts.map((p, i) => (
          <fieldset key={i} className="grid grid-cols-1 items-end gap-2 rounded-md border border-rule p-3 sm:grid-cols-[2fr_1fr_1fr_1fr_auto]">
            <legend className="sr-only">Allocation {i + 1}</legend>
            <Field id={`al-ag-${i}`} label="Agreement">
              <Select id={`al-ag-${i}`} value={p.agreement_id} onChange={(e) => set(i, { agreement_id: e.target.value })}>
                <option value="">Choose…</option>
                {agreements.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </Select>
            </Field>
            <Field id={`al-s-${i}`} label="Period start"><Input id={`al-s-${i}`} type="date" value={p.period_start} onChange={(e) => set(i, { period_start: e.target.value })} /></Field>
            <Field id={`al-e-${i}`} label="Period end"><Input id={`al-e-${i}`} type="date" value={p.period_end} onChange={(e) => set(i, { period_end: e.target.value })} /></Field>
            <Field id={`al-a-${i}`} label="Amount ($)" error={p.amount && !MONEY_RE.test(p.amount) ? "Use digits, e.g. 1250.00 (up to 4 decimals)" : undefined}><Input id={`al-a-${i}`} inputMode="decimal" className="text-right" value={p.amount} onChange={(e) => set(i, { amount: e.target.value.trim() })} /></Field>
            <Button variant="ghost" size="sm" disabled={parts.length === 1} onClick={() => setParts(parts.filter((_, j) => j !== i))}>Remove</Button>
          </fieldset>
        ))}
      </div>
      <Button variant="secondary" size="sm" className="mt-3" onClick={() => setParts([...parts, { agreement_id: "", period_start: "", period_end: "", amount: "" }])} disabled={parts.length >= 50}>Add another period</Button>
    </Dialog>
  );
}

function ManualCredit({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const names = useNames();
  const [f, setF] = useState({ supplier_id: "", reference: "", credit_date: "", amount: "", memo: "" });
  const invalid = !f.supplier_id || !f.reference.trim() || !f.credit_date || !MONEY_RE.test(f.amount);
  const save = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/credits", { body: { ...f, reference: f.reference.trim() } })),
    onSuccess: async () => { toast.success("Credit recorded"); await qc.invalidateQueries({ queryKey: ["credits"] }); onClose(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title="Enter a credit" description="For a credit memo you received outside an import (for example by post)." footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={() => save.mutate()} disabled={invalid} loading={save.isPending}>Save credit</Button></>}>
      <div className="flex flex-col gap-3">
        <Field id="mc-supplier" label="Supplier" required>
          <Select id="mc-supplier" value={f.supplier_id} onChange={(e) => setF({ ...f, supplier_id: e.target.value })}>
            <option value="">Choose…</option>
            {(names.data?.suppliers ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field id="mc-ref" label="Credit memo number" required><Input id="mc-ref" maxLength={100} value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></Field>
          <Field id="mc-date" label="Date" required><Input id="mc-date" type="date" value={f.credit_date} onChange={(e) => setF({ ...f, credit_date: e.target.value })} /></Field>
          <Field id="mc-amount" label="Amount ($)" required error={f.amount && !MONEY_RE.test(f.amount) ? "Use digits, e.g. 1250.00 (up to 4 decimals)" : undefined}><Input id="mc-amount" inputMode="decimal" className="text-right" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value.trim() })} /></Field>
        </div>
        <Field id="mc-memo" label="Memo"><Textarea id="mc-memo" rows={2} maxLength={500} value={f.memo} onChange={(e) => setF({ ...f, memo: e.target.value })} /></Field>
      </div>
    </Dialog>
  );
}

function CreditDrawer({ creditId, onClose, allocate }: { creditId: string | null; onClose: () => void; allocate: boolean }) {
  const qc = useQueryClient();
  const names = useNames();
  const query = useQuery({ queryKey: ["credit", creditId], enabled: !!creditId, queryFn: async () => unwrap(await api.GET("/api/v1/credits/{credit_id}", { params: { path: { credit_id: creditId ?? "" } } })) });
  const [reversing, setReversing] = useState<string | null>(null);
  const reverse = useMutation({
    mutationFn: async (id: string) => unwrap(await api.DELETE("/api/v1/allocations/{allocation_id}", { params: { path: { allocation_id: id } } })),
    onSuccess: async () => {
      setReversing(null);
      toast.success("Allocation reversed");
      await Promise.all([qc.invalidateQueries({ queryKey: ["credit", creditId] }), qc.invalidateQueries({ queryKey: ["credits"] }), qc.invalidateQueries({ queryKey: ["reconciliation"] })]);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Drawer open={creditId !== null} onOpenChange={(o) => !o && onClose()} title="Credit">
      <QueryState query={query}>
        {(c) => (
          <div className="flex flex-col gap-4 text-sm">
            <dl className="grid grid-cols-2 gap-3">
              <div><dt className="text-xs text-muted">Supplier</dt><dd>{names.data?.supplier.get(c.supplier_id) ?? "—"}</dd></div>
              <div><dt className="text-xs text-muted">Reference</dt><dd className="font-mono">{c.credit_reference}</dd></div>
              <div><dt className="text-xs text-muted">Date</dt><dd><DateText value={c.credit_date} /></dd></div>
              <div><dt className="text-xs text-muted">Amount</dt><dd><Money value={c.amount} /></dd></div>
              <div><dt className="text-xs text-muted">Unallocated</dt><dd><Money value={c.unallocated} /></dd></div>
              <div><dt className="text-xs text-muted">Recorded</dt><dd>{formatDateTime(c.created_at)}</dd></div>
            </dl>
            {c.memo ? <p className="text-muted">{c.memo}</p> : null}
            {c.possible_duplicate ? <Notice tone="warning">This may duplicate another credit with the same reference.</Notice> : null}
            <div>
              <h3 className="mb-2 font-semibold">Allocations</h3>
              {c.allocations.length === 0 ? <p className="text-muted">Not allocated yet.</p> : (
                <ul className="divide-y divide-rule rounded-md border border-rule">
                  {c.allocations.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-2 px-3 py-2">
                      <span>{names.data?.agreement.get(a.agreement_id) ?? "Agreement"} · {a.period_start} – {a.period_end} <span className="text-xs text-muted">({a.method})</span></span>
                      <span className="flex items-center gap-2"><Money value={a.amount} />{allocate ? <Button size="sm" variant="ghost" onClick={() => setReversing(a.id)}>Reverse</Button> : null}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <ConfirmDialog open={reversing !== null} onOpenChange={(o) => !o && setReversing(null)} title="Reverse this allocation?" description="The amount returns to unallocated and the period's variance is recalculated. The change is recorded in the audit log." confirmLabel="Reverse" pending={reverse.isPending} onConfirm={() => reversing && reverse.mutate(reversing)} />
          </div>
        )}
      </QueryState>
    </Drawer>
  );
}
