"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Card, Field, Input, Notice, PageHeader, Textarea } from "@/components/ui/core";
import { QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";

type Settings = Record<string, unknown> & { seller?: Record<string, string> };

export default function OpsSettingsPage() {
  const query = useQuery({ queryKey: ["ops", "billing-settings"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/billing-settings")) as Settings });
  return (
    <>
      <PageHeader title="Billing settings" description="Seller details and payment instructions printed on every invoice. They are copied onto each invoice when it is issued." />
      <QueryState query={query}>{(s) => <SettingsForm s={s} />}</QueryState>
    </>
  );
}

function SettingsForm({ s }: { s: Settings }) {
  const qc = useQueryClient();
  const seller = s.seller ?? {};
  const [f, setF] = useState({
    name: seller.name ?? "", address: seller.address ?? "", email: seller.email ?? "", tax_id: seller.tax_id ?? "",
    payment_instructions: String(s.payment_instructions ?? ""), number_prefix: String(s.number_prefix ?? "RL"), payment_terms_days: String(s.payment_terms_days ?? 14), grace_days: String(s.grace_days ?? 14),
  });
  const save = useMutation({
    mutationFn: async () => unwrap(await api.PUT("/api/v1/ops/billing-settings", { body: {
      seller: { name: f.name, address: f.address, email: f.email, tax_id: f.tax_id },
      payment_instructions: f.payment_instructions, number_prefix: f.number_prefix,
      payment_terms_days: Number.parseInt(f.payment_terms_days, 10), grace_days: Number.parseInt(f.grace_days, 10),
    } })),
    onSuccess: () => { toast.success("Billing settings saved"); void qc.invalidateQueries({ queryKey: ["ops", "billing-settings"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card>
      {!s.configured ? <div className="mb-4"><Notice tone="warning" title="Not configured">Values in [brackets] are placeholders. Invoices cannot be issued until they are replaced.</Notice></div> : null}
      <form className="grid max-w-3xl grid-cols-1 gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <Field id="b-name" label="Seller legal name"><Input id="b-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field id="b-email" label="Billing email"><Input id="b-email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field id="b-address" label="Address" className="sm:col-span-2"><Textarea id="b-address" rows={2} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></Field>
        <Field id="b-tax" label="Tax ID (optional)"><Input id="b-tax" value={f.tax_id} onChange={(e) => setF({ ...f, tax_id: e.target.value })} /></Field>
        <Field id="b-prefix" label="Invoice number prefix" hint="2–6 capital letters, e.g. RL → RL-2026-0001"><Input id="b-prefix" value={f.number_prefix} onChange={(e) => setF({ ...f, number_prefix: e.target.value.toUpperCase() })} /></Field>
        <Field id="b-instr" label="Payment instructions" className="sm:col-span-2"><Textarea id="b-instr" rows={4} value={f.payment_instructions} onChange={(e) => setF({ ...f, payment_instructions: e.target.value })} /></Field>
        <Field id="b-terms" label="Payment terms (days)"><Input id="b-terms" inputMode="numeric" value={f.payment_terms_days} onChange={(e) => setF({ ...f, payment_terms_days: e.target.value.replace(/\D/g, "") })} /></Field>
        <Field id="b-grace" label="Grace before suspension may be considered (days)" hint="Proposed default 14. Suspension is always a manual decision."><Input id="b-grace" inputMode="numeric" value={f.grace_days} onChange={(e) => setF({ ...f, grace_days: e.target.value.replace(/\D/g, "") })} /></Field>
        <div><Button type="submit" loading={save.isPending}>Save settings</Button></div>
      </form>
    </Card>
  );
}
