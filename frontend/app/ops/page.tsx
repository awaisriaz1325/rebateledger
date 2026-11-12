"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { DataTable } from "@/components/data-table";
import { Button, Card, Field, Input, PageHeader, Select } from "@/components/ui/core";
import { StatusBadge } from "@/components/ui/finance";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export default function OpsTenantsPage() {
  const router = useRouter();
  const query = useQuery({ queryKey: ["ops", "tenants"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/tenants")) });
  return (
    <>
      <PageHeader title="Organizations" description="Metadata, plan and aggregate usage only. Business data is visible only inside a support session the organization has granted." />
      <CreateTenant />
      <div className="mt-6">
        <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No organizations yet" />}>
          {(rows) => (
            <DataTable
              label="Organizations"
              rows={rows}
              rowKey={(r) => r.id}
              onRowClick={(r) => router.push(`/ops/tenants/${r.id}`)}
              columns={[
                { id: "name", header: "Organization", value: (r) => r.name, cell: (r) => <Link href={`/ops/tenants/${r.id}`} className="font-medium hover:underline">{r.name}{r.is_demo ? <span className="ml-2 text-xs text-muted">(demo)</span> : null}</Link> },
                { id: "plan", header: "Plan", value: (r) => r.plan ?? "" },
                { id: "status", header: "Status", value: (r) => r.status ?? "", cell: (r) => (r.status ? <StatusBadge status={r.status} /> : <span className="text-muted">none</span>) },
                { id: "members", header: "Members", value: (r) => r.members, align: "right" },
                { id: "agreements", header: "Active agreements", value: (r) => r.active_agreements, align: "right" },
                { id: "lines", header: "Purchase lines", value: (r) => r.purchase_lines, align: "right", cell: (r) => r.purchase_lines.toLocaleString("en-US") },
                { id: "claims", header: "Open claims", value: (r) => r.open_claims, align: "right" },
                { id: "import", header: "Last import", value: (r) => r.last_import_at ?? "", cell: (r) => (r.last_import_at ? formatDateTime(r.last_import_at) : "—") },
                { id: "run", header: "Last run", value: (r) => r.last_run_at ?? "", cell: (r) => (r.last_run_at ? formatDateTime(r.last_run_at) : "—") },
              ]}
            />
          )}
        </QueryState>
      </div>
    </>
  );
}

function CreateTenant() {
  const qc = useQueryClient();
  const plans = useQuery({ queryKey: ["ops", "plans"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/plans")) });
  const [f, setF] = useState({ name: "", owner_email: "", billing_email: "", plan_code: "pilot", timezone: "America/Chicago" });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/ops/tenants", { body: { ...f, billing_email: f.billing_email || null } })),
    onSuccess: (t) => {
      toast.success(`${t.name} created; the owner invitation was emailed`);
      setF({ ...f, name: "", owner_email: "", billing_email: "" });
      void qc.invalidateQueries({ queryKey: ["ops", "tenants"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Create an organization">
      <form className="grid grid-cols-1 items-end gap-3 sm:grid-cols-5" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <Field id="t-name" label="Organization name" required><Input id="t-name" value={f.name} maxLength={200} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field id="t-owner" label="First owner's email" required><Input id="t-owner" type="email" value={f.owner_email} onChange={(e) => setF({ ...f, owner_email: e.target.value })} /></Field>
        <Field id="t-billing" label="Billing email" hint="Defaults to the owner."><Input id="t-billing" type="email" value={f.billing_email} onChange={(e) => setF({ ...f, billing_email: e.target.value })} /></Field>
        <Field id="t-plan" label="Plan">
          <Select id="t-plan" value={f.plan_code} onChange={(e) => setF({ ...f, plan_code: e.target.value })}>
            {(plans.data ?? []).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
          </Select>
        </Field>
        <Button type="submit" loading={create.isPending} disabled={!f.name.trim() || !f.owner_email.includes("@")}>Create and invite</Button>
      </form>
    </Card>
  );
}
