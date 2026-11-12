"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Card, Checkbox, Field, Input, Notice, PageHeader } from "@/components/ui/core";
import { Money } from "@/components/ui/finance";
import { QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import type { components } from "@/generated/api";

type Plan = components["schemas"]["PlanOut"];
type PlanIn = components["schemas"]["PlanIn"];
const LIMITS = [["max_active_agreements", "Active agreements"], ["max_users", "Users"], ["max_import_rows_per_month", "Import rows / month"], ["max_storage_mb", "Storage (MB)"]] as const;

export default function OpsPlansPage() {
  const query = useQuery({ queryKey: ["ops", "plans"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/plans")) });
  return (
    <>
      <PageHeader title="Plans" description="The plan catalog lives in the database. Prices are proposed defaults until the founder confirms them." />
      <div className="mb-4"><Notice tone="info">Changing a plan affects every organization on it. Codes cannot change once created.</Notice></div>
      <QueryState query={query}>
        {(plans) => (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {plans.map((p) => <PlanForm key={p.id} plan={p} />)}
            <PlanForm />
          </div>
        )}
      </QueryState>
    </>
  );
}

function blank(n: number | null | undefined): string {
  return n == null ? "" : String(n);
}

function PlanForm({ plan }: { plan?: Plan }) {
  const qc = useQueryClient();
  const [f, setF] = useState({
    code: plan?.code ?? "", name: plan?.name ?? "", monthly_price: plan?.monthly_price ?? "", is_public: plan?.is_public ?? true, sort_order: String(plan?.sort_order ?? 0),
    max_active_agreements: blank(plan?.max_active_agreements), max_users: blank(plan?.max_users), max_import_rows_per_month: blank(plan?.max_import_rows_per_month), max_storage_mb: blank(plan?.max_storage_mb),
  });
  const save = useMutation({
    mutationFn: async () => {
      const num = (v: string) => (v.trim() === "" ? null : Number.parseInt(v, 10));
      const body: PlanIn = { code: f.code, name: f.name, monthly_price: f.monthly_price, is_public: f.is_public, sort_order: num(f.sort_order) ?? 0, max_active_agreements: num(f.max_active_agreements), max_users: num(f.max_users), max_import_rows_per_month: num(f.max_import_rows_per_month), max_storage_mb: num(f.max_storage_mb) };
      return plan
        ? unwrap(await api.PATCH("/api/v1/ops/plans/{plan_id}", { params: { path: { plan_id: plan.id } }, body }))
        : unwrap(await api.POST("/api/v1/ops/plans", { body }));
    },
    onSuccess: () => { toast.success("Plan saved"); void qc.invalidateQueries({ queryKey: ["ops", "plans"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const id = plan?.code ?? "new";
  return (
    <Card title={plan ? <>{plan.name} <span className="text-sm font-normal text-muted">· <Money value={plan.monthly_price} />/month</span></> : "New plan"}>
      <form className="grid grid-cols-2 gap-3 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <Field id={`${id}-code`} label="Code"><Input id={`${id}-code`} value={f.code} disabled={!!plan} onChange={(e) => setF({ ...f, code: e.target.value.toLowerCase() })} /></Field>
        <Field id={`${id}-name`} label="Name"><Input id={`${id}-name`} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field id={`${id}-price`} label="Monthly price (USD)"><Input id={`${id}-price`} inputMode="decimal" className="text-right" value={f.monthly_price} onChange={(e) => setF({ ...f, monthly_price: e.target.value.trim() })} /></Field>
        {LIMITS.map(([k, label]) => (
          <Field key={k} id={`${id}-${k}`} label={label} hint="Empty = unlimited"><Input id={`${id}-${k}`} inputMode="numeric" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value.replace(/\D/g, "") })} /></Field>
        ))}
        <Field id={`${id}-sort`} label="Sort order"><Input id={`${id}-sort`} inputMode="numeric" value={f.sort_order} onChange={(e) => setF({ ...f, sort_order: e.target.value.replace(/\D/g, "") })} /></Field>
        <div className="flex items-end pb-2"><Checkbox id={`${id}-public`} label="Shown on pricing page" checked={f.is_public} onChange={(e) => setF({ ...f, is_public: e.target.checked })} /></div>
        <div className="col-span-full"><Button type="submit" size="sm" loading={save.isPending} disabled={!f.code || !f.name || !/^\d+(\.\d{1,4})?$/.test(f.monthly_price)}>{plan ? "Save" : "Create plan"}</Button></div>
      </form>
    </Card>
  );
}
