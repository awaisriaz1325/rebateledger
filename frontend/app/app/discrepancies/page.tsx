"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Checkbox, Field, Input, PageHeader, Select } from "@/components/ui/core";
import { ReconTable } from "@/components/recon-table";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { useNames } from "@/lib/queries";

const MONEY_RE = /^\d{1,14}(\.\d{1,4})?$/;

export default function DiscrepanciesPage() {
  const names = useNames();
  const members = useQuery({ queryKey: ["members"], queryFn: async () => unwrap(await api.GET("/api/v1/org/members")) });
  const [supplier, setSupplier] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [minAmount, setMinAmount] = useState("");
  const [minAge, setMinAge] = useState("");
  const [assignee, setAssignee] = useState("");
  const [unclaimed, setUnclaimed] = useState(false);
  const amountOk = minAmount === "" || MONEY_RE.test(minAmount);
  const query = useQuery({
    queryKey: ["discrepancies", supplier, status, from, to, amountOk ? minAmount : "", minAge, assignee, unclaimed],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/discrepancies", {
          params: {
            query: {
              supplier_id: supplier || undefined,
              status: status || undefined,
              period_from: from || undefined,
              period_to: to || undefined,
              min_amount: amountOk && minAmount ? minAmount : undefined,
              min_age_days: minAge ? Number.parseInt(minAge, 10) : undefined,
              assignee_id: assignee || undefined,
              unclaimed: unclaimed || undefined,
            },
          },
        }),
      ),
  });
  return (
    <>
      <PageHeader title="Discrepancies" description="Periods where suppliers paid less than expected, nothing at all, or more. Select rows to open a claim." />
      <div className="mb-4 grid grid-cols-2 items-end gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <Field id="d-supplier" label="Supplier">
          <Select id="d-supplier" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
            <option value="">All</option>
            {(names.data?.suppliers ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
        </Field>
        <Field id="d-status" label="Status">
          <Select id="d-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option><option value="SHORT_PAID">Short-paid</option><option value="MISSING">Missing</option><option value="OVERPAID">Overpaid</option>
          </Select>
        </Field>
        <Field id="d-from" label="Period from"><Input id="d-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field id="d-to" label="Period to"><Input id="d-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <Field id="d-min" label="Min. variance ($)" error={amountOk ? undefined : "Enter an amount like 250 or 250.00"}><Input id="d-min" inputMode="decimal" value={minAmount} onChange={(e) => setMinAmount(e.target.value.trim())} /></Field>
        <Field id="d-age" label="Min. days past due"><Input id="d-age" inputMode="numeric" value={minAge} onChange={(e) => setMinAge(e.target.value.replace(/\D/g, ""))} /></Field>
        <Field id="d-assignee" label="Claim assignee">
          <Select id="d-assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
            <option value="">Anyone</option>
            {(members.data ?? []).map((m) => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
          </Select>
        </Field>
        <div className="pb-2"><Checkbox id="d-unclaimed" label="Not yet claimed" checked={unclaimed} onChange={(e) => setUnclaimed(e.target.checked)} /></div>
      </div>
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No discrepancies">Every period in scope matches within tolerance, or nothing matches these filters.</EmptyState>}>
        {(rows) => <ReconTable rows={rows} label="Discrepancies" exportName="discrepancies" />}
      </QueryState>
    </>
  );
}
