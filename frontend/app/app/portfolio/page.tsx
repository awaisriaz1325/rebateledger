"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button, PageHeader } from "@/components/ui/core";
import { Money } from "@/components/ui/finance";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useRefreshSession } from "@/lib/session";

/** Advisor portfolio (v1.3 Phase 29): each organization is read with its own access rules. */
export default function PortfolioPage() {
  const router = useRouter();
  const refresh = useRefreshSession();
  const [opening, setOpening] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["portfolio"], queryFn: async () => unwrap(await api.GET("/api/v1/me/portfolio")) });

  async function open(id: string) {
    setOpening(id);
    try {
      await refresh(unwrap(await api.POST("/api/v1/auth/switch-organization", { body: { organization_id: id } })));
      router.push("/app");
    } catch (e) {
      toast.error(errorMessage(e));
      setOpening(null);
    }
  }

  return (
    <>
      <PageHeader title="All organizations" description="One line per organization you belong to. Identified amounts are what each organization's latest calculation found, not money recovered." />
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No organizations">You are not a member of any organization.</EmptyState>}>
        {(rows) => (
          <div className="overflow-x-auto rounded-lg border border-rule bg-surface">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Your organizations</caption>
              <thead>
                <tr className="border-b border-rule text-xs text-muted">
                  <th scope="col" className="px-4 py-2">Organization</th>
                  <th scope="col" className="pr-4">Your role</th>
                  <th scope="col" className="pr-4 text-right">Identified open variance</th>
                  <th scope="col" className="pr-4 text-right">Short-paid / missing</th>
                  <th scope="col" className="pr-4 text-right">Open claims</th>
                  <th scope="col" className="pr-4">Last calculation</th>
                  <th scope="col"><span className="sr-only">Action</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => (
                  <tr key={o.tenant_id} className="border-b border-rule last:border-0">
                    <td className="px-4 py-2 font-medium">{o.name}{o.current ? <span className="ml-2 text-xs font-normal text-muted">(current)</span> : null}</td>
                    <td className="pr-4 capitalize">{o.role}</td>
                    {o.locked ? (
                      <td className="pr-4 text-muted" colSpan={4}>Two-factor sign-in is required here. Open it to set it up; figures appear afterwards.</td>
                    ) : (
                      <>
                        <td className="pr-4 text-right"><Money value={o.identified_open_variance} /></td>
                        <td className="num pr-4">{o.short_paid} / {o.missing}</td>
                        <td className="num pr-4">{o.open_claims}</td>
                        <td className="pr-4">{o.last_run_at ? formatDateTime(o.last_run_at) : <span className="text-muted">Never</span>}</td>
                      </>
                    )}
                    <td className="py-2 pr-4 text-right">
                      {o.current ? null : <Button size="sm" variant="secondary" loading={opening === o.tenant_id} disabled={opening !== null} onClick={() => void open(o.tenant_id)} aria-label={`Open ${o.name}`}>Open</Button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryState>
    </>
  );
}
