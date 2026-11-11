"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { DataTable } from "@/components/data-table";
import { Notice, PageHeader } from "@/components/ui/core";
import { DateText, Estimate, Money, Qty, StatusBadge } from "@/components/ui/finance";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";

export default function TiersPage() {
  const query = useQuery({ queryKey: ["tiers"], queryFn: async () => unwrap(await api.GET("/api/v1/tiers")) });
  const asOf = query.data?.map((t) => t.data_as_of).filter(Boolean).sort().at(-1);
  return (
    <>
      <PageHeader title="Tier tracker" description="Open periods of tiered agreements: where you are now, the next threshold, and a straight-line projection to period end." />
      <div className="mb-4">
        <Notice tone="info" title="Projections are estimates">They assume purchases continue at the same daily pace as so far this period. They are not a forecast and are never used in calculations.{asOf ? <> Data as of <DateText value={asOf} />.</> : null}</Notice>
      </div>
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No open tiered periods">Tiered agreements with a period in progress appear here.</EmptyState>}>
        {(rows) => (
          <DataTable
            label="Tier tracker"
            rows={rows}
            rowKey={(r) => `${r.agreement_id}-${r.period_start}`}
            exportName="tier-tracker"
            columns={[
              { id: "agreement", header: "Agreement", value: (r) => r.agreement_name, cell: (r) => <Link href={`/app/agreements/${r.agreement_id}`} className="font-medium hover:underline">{r.agreement_name}</Link> },
              { id: "supplier", header: "Supplier", value: (r) => r.supplier_name },
              { id: "period", header: "Period", value: (r) => r.period_start, cell: (r) => <span><DateText value={r.period_start} /> – <DateText value={r.period_end} /></span> },
              { id: "measure", header: "So far", value: (r) => r.current_measure, numeric: true, align: "right", cell: (r) => (r.measure_kind === "quantity" ? <Qty value={r.current_measure} /> : <Money value={r.current_measure} />) },
              { id: "tier", header: "Tier now", value: (r) => r.current_tier ?? "", align: "right", cell: (r) => (r.current_tier ? `Tier ${r.current_tier}` : <span className="text-muted">None</span>) },
              { id: "gap", header: "To next tier", value: (r) => r.gap ?? "", numeric: true, align: "right", cell: (r) => (r.gap == null ? <span className="text-muted">Top tier</span> : r.measure_kind === "quantity" ? <Qty value={r.gap} /> : <Money value={r.gap} />) },
              { id: "days", header: "Days left", value: (r) => r.days_remaining, align: "right" },
              { id: "projected", header: "Projected", value: (r) => r.projected_measure, numeric: true, align: "right", cell: (r) => <span className="inline-flex items-center gap-1">{r.measure_kind === "quantity" ? <Qty value={r.projected_measure} /> : <Money value={r.projected_measure} />}<Estimate /></span> },
              { id: "reach", header: "On pace?", value: (r) => (r.next_tier == null ? "" : r.projected_reaches_next ? "yes" : "no"), cell: (r) => (r.next_tier == null ? null : r.projected_reaches_next ? <span className="text-positive">On pace for tier {r.next_tier}</span> : <span className="text-warning">Below pace</span>) },
              { id: "upside", header: "Extra rebate at next tier", value: (r) => r.potential_additional ?? "", numeric: true, align: "right", cell: (r) => (r.potential_additional == null ? <span className="text-muted">—</span> : <span className="inline-flex items-center gap-1"><Money value={r.potential_additional} /><Estimate /></span>) },
              { id: "review", header: "", value: (r) => (r.needs_review ? "NEEDS_REVIEW" : ""), cell: (r) => (r.needs_review ? <StatusBadge status="NEEDS_REVIEW" /> : null) },
            ]}
          />
        )}
      </QueryState>
    </>
  );
}
