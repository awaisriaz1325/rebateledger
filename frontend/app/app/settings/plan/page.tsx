"use client";

import { useQuery } from "@tanstack/react-query";
import { DateText, Money, StatusBadge } from "@/components/ui/finance";
import { Card } from "@/components/ui/core";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";

const LABELS: Record<string, [string, string]> = {
  max_active_agreements: ["Active agreements", "active_agreements"],
  max_users: ["Users", "users"],
  max_import_rows_per_month: ["Imported rows this month", "import_rows_this_month"],
  max_storage_mb: ["Stored files (MB)", "storage_mb"],
};

export default function PlanPage() {
  const query = useQuery({ queryKey: ["plan"], queryFn: async () => unwrap(await api.GET("/api/v1/org/plan")) });
  return (
    <div className="flex flex-col gap-6">
    <Card title="Plan & usage">
      <QueryState query={query}>
        {(p) => (
          <>
            {p.plan_name ? (
              <p className="mb-4 text-sm">Plan: <strong>{p.plan_name}</strong> {p.status ? <StatusBadge status={p.status} /> : null}</p>
            ) : (
              <p className="mb-4 text-sm text-muted">No plan is assigned yet; your account manager sets this up.</p>
            )}
            <dl className="grid max-w-xl grid-cols-1 gap-3 sm:grid-cols-2">
              {Object.entries(LABELS).map(([limitKey, [label, usageKey]]) => {
                const used = p.usage[usageKey] ?? 0;
                const limit = p.limits[limitKey];
                return (
                  <div key={limitKey} className="rounded-md border border-rule p-3">
                    <dt className="text-xs text-muted">{label}</dt>
                    <dd className="num mt-1 text-left text-lg font-semibold">{used.toLocaleString("en-US")}{limit != null ? <span className="text-sm font-normal text-muted"> of {limit.toLocaleString("en-US")}</span> : null}</dd>
                  </div>
                );
              })}
            </dl>
            <p className="mt-4 text-xs text-muted">Limits block only new actions; existing data always stays available.</p>
          </>
        )}
      </QueryState>
    </Card>
    <Invoices />
    </div>
  );
}

function Invoices() {
  const query = useQuery({ queryKey: ["invoices"], queryFn: async () => unwrap(await api.GET("/api/v1/billing/invoices")) });
  return (
    <section id="invoices">
      <Card title="Invoices">
        <QueryState query={query} isEmpty={(i) => i.length === 0} empty={<EmptyState title="No invoices yet">Invoices are issued by the RebateLedger team and appear here.</EmptyState>}>
          {(rows) => (
            <table className="w-full text-sm" aria-label="Invoices">
              <thead><tr className="text-left text-xs text-muted uppercase"><th className="py-1">Invoice</th><th>Issued</th><th>Due</th><th>Status</th><th className="text-right">Total</th><th /></tr></thead>
              <tbody>
                {rows.map((i) => (
                  <tr key={i.id} className="border-t border-rule">
                    <td className="py-2 font-mono">{i.number}</td>
                    <td><DateText value={i.issue_date} /></td>
                    <td><DateText value={i.due_date} /></td>
                    <td><StatusBadge status={i.status} />{i.status === "paid" && i.paid_on ? <span className="ml-2 text-xs text-muted">on {i.paid_on}</span> : null}</td>
                    <td className="text-right"><Money value={i.total} /></td>
                    <td className="text-right"><a className="text-brand underline" href={`/api/v1/billing/invoices/${i.id}/pdf`}>PDF</a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </QueryState>
      </Card>
    </section>
  );
}
