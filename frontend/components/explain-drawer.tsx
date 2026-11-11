"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Notice, Select } from "@/components/ui/core";
import { DateText, Money, StatusBadge } from "@/components/ui/finance";
import { Drawer } from "@/components/ui/overlay";
import { QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDate, formatQuantity } from "@/lib/format";
import { can, useSession } from "@/lib/session";
import type { PreviewResult, ResultDetail } from "@/lib/types";

type Explained = Pick<ResultDetail, "period_start" | "period_end" | "full_period_start" | "full_period_end" | "expected" | "expected_unrounded" | "spend" | "quantity" | "measure" | "tier_reached" | "statuses" | "reasons" | "excluded_counts" | "trace" | "engine_version" | "input_hash"> & { eligible_count: number };

/** "Explain" for any expected amount (SPEC §10): steps, tier, measure, counts, engine version. */
export function ExplainDrawer({ resultId, open, onOpenChange }: { resultId: string | null; open: boolean; onOpenChange: (o: boolean) => void }) {
  const query = useQuery({
    queryKey: ["result", resultId],
    enabled: open && !!resultId,
    queryFn: async () => unwrap(await api.GET("/api/v1/results/{result_id}", { params: { path: { result_id: resultId ?? "" } } })),
  });
  return (
    <Drawer open={open} onOpenChange={onOpenChange} title="How this amount was calculated" description="Every step of the calculation, with the numbers used. You can recompute it by hand.">
      <QueryState query={query}>
        {(r) => (
          <>
            <p className="mb-4 text-sm text-muted">
              Run {r.run_number} · version {r.version_no} · <Link className="text-brand hover:underline" href={`/app/agreements/${r.agreement_id}`}>open agreement</Link>
            </p>
            {r.stale_at ? <div className="mb-4"><Notice tone="warning" title="Stale">{r.stale_reason}. Re-run to update this result.</Notice></div> : null}
            <ResolveVersionChange r={r} />
            <ExplainBody r={r} />
          </>
        )}
      </QueryState>
    </Drawer>
  );
}

function ResolveVersionChange({ r }: { r: ResultDetail }) {
  const session = useSession();
  const qc = useQueryClient();
  const [choice, setChoice] = useState<"split" | "apply_old" | "apply_new">("split");
  const save = useMutation({
    mutationFn: async () => unwrap(await api.PUT("/api/v1/version-resolutions", { body: { agreement_id: r.agreement_id, period_start: r.full_period_start, period_end: r.full_period_end, choice } })),
    onSuccess: () => { toast.success("Decision saved. Start a new run to apply it."); void qc.invalidateQueries(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!r.reasons.some((x) => x.code === "VERSION_CHANGE_IN_PERIOD") || !can(session, "edit_agreements")) return null;
  return (
    <div className="mb-4 rounded-md border border-info/30 bg-info-soft p-4">
      <p className="mb-2 text-sm font-semibold">The agreement’s terms changed inside this period. Decide how to measure it:</p>
      <div className="flex flex-wrap items-end gap-2">
        <label htmlFor="resolution" className="sr-only">Decision</label>
        <Select id="resolution" value={choice} onChange={(e) => setChoice(e.target.value as typeof choice)} className="max-w-sm">
          <option value="split">Split the period at the change date</option>
          <option value="apply_old">Apply the old terms to the whole period</option>
          <option value="apply_new">Apply the new terms to the whole period</option>
        </Select>
        <Button onClick={() => save.mutate()} loading={save.isPending}>Save decision</Button>
      </div>
    </div>
  );
}

export function ExplainBody({ r }: { r: Explained | PreviewResult }) {
  return (
    <div className="flex flex-col gap-5">
      <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <div><dt className="text-xs text-muted">Expected</dt><dd className="text-lg font-semibold">{r.expected == null ? "Not calculated" : <Money value={r.expected} />}</dd></div>
        <div><dt className="text-xs text-muted">Period</dt><dd><DateText value={r.period_start} /> – <DateText value={r.period_end} /></dd></div>
        <div><dt className="text-xs text-muted">Tier reached</dt><dd>{r.tier_reached ?? "—"}</dd></div>
        <div><dt className="text-xs text-muted">Eligible spend (S)</dt><dd><Money value={r.spend} /></dd></div>
        <div><dt className="text-xs text-muted">Eligible quantity (Q)</dt><dd className="num text-left">{formatQuantity(r.quantity)}</dd></div>
        <div><dt className="text-xs text-muted">Measure (M)</dt><dd className="num text-left">{formatQuantity(r.measure)}</dd></div>
      </dl>
      <div className="flex flex-wrap gap-1">{r.statuses.map((s) => <StatusBadge key={s} status={s} />)}</div>
      {r.reasons.length ? (
        <Notice tone="info" title="Needs a decision">
          <ul className="list-disc pl-4">{r.reasons.map((x, i) => <li key={i}><span className="font-mono text-xs">{x.code}</span> — {x.message}</li>)}</ul>
        </Notice>
      ) : null}
      <section>
        <h3 className="mb-2 text-sm font-semibold">Lines</h3>
        <p className="text-sm">{r.eligible_count.toLocaleString("en-US")} eligible line(s).{" "}
          {Object.keys(r.excluded_counts).length ? <>Excluded: {Object.entries(r.excluded_counts).map(([k, v]) => `${String(v)} ${k.toLowerCase().replaceAll("_", " ")}`).join(", ")}.</> : "None excluded."}
        </p>
        <p className="mt-1 text-xs text-muted">Full period {formatDate(r.full_period_start)} – {formatDate(r.full_period_end)}.</p>
      </section>
      <section>
        <h3 className="mb-2 text-sm font-semibold">Calculation steps</h3>
        <ol className="flex flex-col gap-2">
          {r.trace.map((t, i) => (
            <li key={i} className="rounded-md border border-rule p-3">
              <p className="text-xs font-semibold text-muted uppercase">{t.step}. {t.name.replaceAll("_", " ")}</p>
              <p className="mt-1 text-sm break-words">{t.description}</p>
              {Object.keys(t.values).length ? (
                <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 font-mono text-xs sm:grid-cols-2">
                  {Object.entries(t.values).map(([k, v]) => <div key={k} className="break-all"><dt className="inline text-muted">{k}: </dt><dd className="inline">{String(v)}</dd></div>)}
                </dl>
              ) : null}
            </li>
          ))}
        </ol>
      </section>
      <p className="font-mono text-[11px] break-all text-muted">engine {r.engine_version} · input {r.input_hash}</p>
    </div>
  );
}
