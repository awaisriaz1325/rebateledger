"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button, Card, Notice, PageHeader } from "@/components/ui/core";
import { Money } from "@/components/ui/finance";
import { QueryState } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { components } from "@/generated/api";

type Dashboard = components["schemas"]["DashboardOut"];

export default function DashboardPage() {
  const session = useSession();
  const query = useQuery({ queryKey: ["dashboard"], queryFn: async () => unwrap(await api.GET("/api/v1/dashboard")) });
  return (
    <>
      <PageHeader title="Dashboard" description={`${session.organization?.name ?? ""} · identified amounts are what the system found; recovered amounts are credits you confirmed.`} />
      <Onboarding />
      <QueryState query={query}>{(d) => <Kpis d={d} />}</QueryState>
    </>
  );
}

function Tile({ label, value, sub, href }: { label: string; value: React.ReactNode; sub?: React.ReactNode; href: string }) {
  return (
    <Link href={href} className="group rounded-lg border border-rule bg-surface p-4 hover:border-brand">
      <p className="text-xs font-medium text-muted uppercase">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
      {sub ? <p className="mt-1 text-xs text-muted">{sub}</p> : null}
      <span className="mt-2 inline-block text-xs text-brand group-hover:underline">View list →</span>
    </Link>
  );
}

function Kpis({ d }: { d: Dashboard }) {
  const aging = Object.entries(d.open_claims.aging).map(([bucket, v]) => ({ bucket, count: v.count, amount: v.amount }));
  const staleSuppliers = d.data_freshness.suppliers.filter((s) => s.stale);
  return (
    <div className="flex flex-col gap-6">
      {!d.has_results ? <Notice tone="info" title="No reconciliation yet">Import purchases and credits, then start a run to see your numbers here.</Notice> : null}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile label="Identified open variance" value={<Money value={d.identified_open_variance.amount} />} sub="Short-paid and missing, not yet recovered" href="/app/discrepancies?status=SHORT_PAID,MISSING" />
        <Tile label="Recovered this year" value={<Money value={d.recovered_this_year.amount} />} sub="Credits linked to claims" href="/app/claims?open=false" />
        <Tile label="Open claims" value={<span className="num">{d.open_claims.count}</span>} sub={<>Claimed <Money value={d.open_claims.amount} /></>} href="/app/claims?open=true" />
        <Tile label="Needs review" value={<span className="num">{d.needs_review.count}</span>} sub="Decisions the engine will not guess" href="/app/results?status=NEEDS_REVIEW" />
      </div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card title="Open claims by age (days)">
          <div className="h-48" aria-hidden="true">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={aging} margin={{ left: 0, right: 8, top: 8 }}>
                <CartesianGrid strokeDasharray="2 4" stroke="var(--rule)" vertical={false} />
                <XAxis dataKey="bucket" tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={false} tickLine={false} width={28} />
                <Tooltip cursor={{ fill: "var(--surface-2)" }} contentStyle={{ background: "var(--surface)", border: "1px solid var(--rule)", borderRadius: 6, fontSize: 12 }} />
                <Bar dataKey="count" name="Claims" fill="var(--brand)" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <table className="mt-3 w-full text-sm" aria-label="Open claims by age">
            <thead><tr className="text-left text-xs text-muted"><th>Age</th><th className="text-right">Claims</th><th className="text-right">Claimed</th></tr></thead>
            <tbody>{aging.map((a) => <tr key={a.bucket}><td>{a.bucket} days</td><td className="num">{a.count}</td><td className="num">{formatMoney(a.amount)}</td></tr>)}</tbody>
          </table>
        </Card>
        <Card title="Top suppliers by open variance">
          {d.top_suppliers_by_open_variance.length === 0 ? <p className="text-sm text-muted">Nothing open.</p> : (
            <ul className="divide-y divide-rule">
              {d.top_suppliers_by_open_variance.map((s) => (
                <li key={s.supplier_name} className="flex justify-between py-2 text-sm"><span>{s.supplier_name}</span><Money value={s.amount} /></li>
              ))}
            </ul>
          )}
          <Link href="/app/tiers" className="mt-4 inline-block text-sm text-brand hover:underline">{d.tier_opportunities.count} tier opportunit{d.tier_opportunities.count === 1 ? "y" : "ies"} close to the next tier →</Link>
        </Card>
      </div>
      <Card title="Data freshness" actions={<span className="text-xs text-muted">Warn after {d.data_freshness.threshold_days} days</span>}>
        {staleSuppliers.length ? <div className="mb-3"><Notice tone="warning">{staleSuppliers.length} supplier(s) have no purchases in the last {d.data_freshness.threshold_days} days. Results may be incomplete until you import newer data.</Notice></div> : null}
        <table className="w-full text-sm" aria-label="Latest purchase date per supplier">
          <thead><tr className="text-left text-xs text-muted uppercase"><th className="py-1">Supplier</th><th>Latest purchase</th><th className="text-right">Age (days)</th></tr></thead>
          <tbody>
            {d.data_freshness.suppliers.map((s) => (
              <tr key={s.supplier_id} className="border-t border-rule">
                <td className="py-1.5"><Link href={`/app/suppliers/${s.supplier_id}`} className="hover:underline">{s.supplier_name}</Link></td>
                <td>{s.latest_purchase_date ? formatDate(s.latest_purchase_date) : "No data"}</td>
                <td className={`num ${s.stale ? "text-warning font-medium" : ""}`}>{s.days_old ?? "—"}{s.stale ? " (old)" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-muted">As of {formatDate(d.as_of)}</p>
      </Card>
    </div>
  );
}

const STEPS = [
  { key: "supplier", label: "Add a supplier", href: "/app/suppliers/new" },
  { key: "agreement", label: "Add an agreement", href: "/app/agreements/new" },
  { key: "purchases", label: "Import purchases", href: "/app/imports/new?type=purchases" },
  { key: "credits", label: "Import credits", href: "/app/imports/new?type=credits" },
  { key: "run", label: "Run a reconciliation", href: "/app/runs" },
  { key: "review", label: "Review results", href: "/app/results" },
] as const;

/** Onboarding checklist (SPEC §4.2): progress derived from real data; dismissal saved. */
function Onboarding() {
  const qc = useQueryClient();
  const org = useQuery({ queryKey: ["org"], queryFn: async () => unwrap(await api.GET("/api/v1/org")) });
  const progress = useQuery({
    queryKey: ["onboarding-progress"],
    enabled: !!org.data && !org.data.onboarding?.dismissed,
    queryFn: async () => {
      const [s, a, p, c, r] = await Promise.all([
        api.GET("/api/v1/suppliers", { params: { query: { limit: 1 } } }),
        api.GET("/api/v1/agreements", { params: { query: { limit: 1 } } }),
        api.GET("/api/v1/imports", { params: { query: { import_type: "purchases", limit: 1 } } }),
        api.GET("/api/v1/imports", { params: { query: { import_type: "credits", limit: 1 } } }),
        api.GET("/api/v1/runs", { params: { query: { limit: 1 } } }),
      ]);
      const has = (x: { data?: { items: unknown[] } }) => (x.data?.items.length ?? 0) > 0;
      const ran = has(r);
      return { supplier: has(s), agreement: has(a), purchases: has(p), credits: has(c), run: ran, review: ran };
    },
  });
  const dismiss = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/org/onboarding", { body: { dismissed: true } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["org"] }),
  });
  if (!org.data || org.data.onboarding?.dismissed || !progress.data) return null;
  const done = STEPS.filter((s) => progress.data[s.key]).length;
  if (done === STEPS.length) return null;
  return (
    <Card className="mb-6" title={`Get started — ${done} of ${STEPS.length} done`} actions={<Button variant="ghost" size="sm" onClick={() => dismiss.mutate()}>Dismiss</Button>}>
      <ol className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {STEPS.map((s) => {
          const ok = progress.data[s.key];
          return (
            <li key={s.key}>
              <Link href={s.href} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-2">
                {ok ? <CheckCircle2 size={16} className="text-positive" aria-hidden="true" /> : <Circle size={16} className="text-muted" aria-hidden="true" />}
                <span className={ok ? "text-muted line-through" : ""}>{s.label}</span>
                <span className="sr-only">{ok ? "(done)" : "(to do)"}</span>
              </Link>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
