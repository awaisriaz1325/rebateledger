"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Card, Field, Notice, PageHeader } from "@/components/ui/core";
import { PermissionDenied, QueryState } from "@/components/ui/states";
import { api, ApiError, idempotencyKey, unwrap, uploadForm } from "@/lib/api";
import { can, useSession } from "@/lib/session";
import type { BulkColumn, BulkPlan } from "@/lib/types";

const ACTIONS: Record<string, string> = { create: "Create draft", new_version: "New draft version", unchanged: "No change" };

/** Bulk agreement import (v1.2 Phase 21): preview, then create drafts — all or nothing. */
export default function ImportAgreementsPage() {
  const session = useSession();
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [plan, setPlan] = useState<BulkPlan | null>(null);
  const [busy, setBusy] = useState<"preview" | "commit" | null>(null);
  if (!can(session, "edit_agreements")) return <PermissionDenied />;

  async function send(path: "/api/v1/agreements/bulk/preview" | "/api/v1/agreements/bulk") {
    if (!file) return null;
    const form = new FormData();
    form.append("file", file);
    return uploadForm<BulkPlan>(path, form, path.endsWith("/bulk") ? { "Idempotency-Key": idempotencyKey() } : {});
  }

  async function preview() {
    setBusy("preview");
    try {
      setPlan(await send("/api/v1/agreements/bulk/preview"));
    } catch (e) {
      setPlan(null);
      toast.error(e instanceof ApiError ? e.problem.detail || e.problem.title : "Preview failed");
    } finally {
      setBusy(null);
    }
  }

  async function commit() {
    setBusy("commit");
    try {
      const done = await send("/api/v1/agreements/bulk");
      const n = done?.items.filter((i) => i.action !== "unchanged").length ?? 0;
      toast.success(`${n} draft${n === 1 ? "" : "s"} created. Review and activate each one.`);
      router.push("/app/agreements");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.problem.detail || e.problem.title : "Import failed");
    } finally {
      setBusy(null);
    }
  }

  const toCreate = plan ? plan.items.filter((i) => i.action !== "unchanged").length : 0;
  return (
    <>
      <PageHeader title="Import agreements" description="Load many rebate programs from one CSV file. Every agreement is created as a draft: nothing is used in calculations until someone reviews and activates it." />
      <div className="flex flex-col gap-6">
        <Card title="1. Prepare the file">
          <p className="text-sm text-muted">
            One row per tier, or one row per component that has no tiers. Rows with the same <code>agreement_ref</code> form one agreement and must repeat the same agreement settings. Eligibility rules and custom periods are added in the editor afterwards.
          </p>
          <p className="mt-3"><a href="/api/v1/agreements/bulk/template" download className="text-sm font-medium text-brand underline">Download the CSV template</a></p>
          <ColumnGuide />
        </Card>

        <Card title="2. Upload and preview">
          <form className="flex flex-wrap items-end gap-4" onSubmit={(e) => { e.preventDefault(); void preview(); }}>
            <Field id="agreements-file" label="CSV file" hint="UTF-8 CSV, up to 1 MB and 2,000 rows.">
              <input id="agreements-file" type="file" accept=".csv,.txt" className="text-sm" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPlan(null); }} />
            </Field>
            <Button type="submit" disabled={!file} loading={busy === "preview"}>Preview</Button>
          </form>
        </Card>

        {plan ? <Result plan={plan} /> : null}

        {plan ? (
          <Card title="3. Create drafts">
            {plan.errors.length ? (
              <Notice tone="negative" title="Fix the file first">Nothing will be created while any row has a problem.</Notice>
            ) : toCreate === 0 ? (
              <Notice tone="info">Every agreement in this file already has a draft with the same terms. There is nothing to create.</Notice>
            ) : (
              <div className="flex flex-wrap items-center gap-4">
                <Button onClick={() => void commit()} loading={busy === "commit"}>Create {toCreate} draft{toCreate === 1 ? "" : "s"}</Button>
                <span className="text-sm text-muted">Then open each agreement, check it, and request activation.</span>
              </div>
            )}
          </Card>
        ) : null}
        <p className="text-sm"><Link href="/app/agreements" className="text-brand underline">Back to agreements</Link></p>
      </div>
    </>
  );
}

function ColumnGuide() {
  const query = useQuery({ queryKey: ["agreement-bulk-columns"], queryFn: async () => unwrap(await api.GET("/api/v1/agreements/bulk/columns")) });
  return (
    <details className="mt-4">
      <summary className="cursor-pointer text-sm font-medium">Column guide</summary>
      <div className="mt-3 overflow-x-auto">
        <QueryState query={query}>
          {(cols: BulkColumn[]) => (
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Columns of the agreement import file</caption>
              <thead><tr className="border-b border-rule text-xs text-muted"><th scope="col" className="py-2 pr-4">Column</th><th scope="col" className="pr-4">Required</th><th scope="col" className="pr-4">Meaning</th><th scope="col">Allowed values</th></tr></thead>
              <tbody>
                {cols.map((c) => (
                  <tr key={c.name} className="border-b border-rule align-top last:border-0">
                    <td className="py-2 pr-4 font-mono text-xs">{c.name}</td>
                    <td className="pr-4">{c.required ? "Yes" : "No"}</td>
                    <td className="pr-4 text-muted">{c.help}</td>
                    <td className="font-mono text-xs">{c.allowed.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </QueryState>
      </div>
    </details>
  );
}

function Result({ plan }: { plan: BulkPlan }) {
  return (
    <>
      {plan.errors.length ? (
        <Card title={`Problems (${plan.errors.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Problems found in the file</caption>
              <thead><tr className="border-b border-rule text-xs text-muted"><th scope="col" className="py-2 pr-4">Row</th><th scope="col" className="pr-4">Column</th><th scope="col">Problem</th></tr></thead>
              <tbody>
                {plan.errors.map((e, i) => (
                  <tr key={i} className="border-b border-rule last:border-0">
                    <td className="num py-2 pr-4">{e.row ?? "—"}</td>
                    <td className="pr-4 font-mono text-xs">{e.column ?? "—"}</td>
                    <td>{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}
      <Card title={`Agreements in the file (${plan.items.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Agreements that the file would create or update</caption>
            <thead><tr className="border-b border-rule text-xs text-muted"><th scope="col" className="py-2 pr-4">Reference</th><th scope="col" className="pr-4">Name</th><th scope="col" className="pr-4">Supplier</th><th scope="col" className="pr-4">Result</th><th scope="col" className="pr-4">Terms</th></tr></thead>
            <tbody>
              {plan.items.map((i) => (
                <tr key={i.ref} className="border-b border-rule align-top last:border-0">
                  <td className="py-2 pr-4 font-mono text-xs">{i.ref}</td>
                  <td className="pr-4">{i.name}</td>
                  <td className="pr-4">{i.supplier_name}</td>
                  <td className="pr-4">{ACTIONS[i.action] ?? i.action}</td>
                  <td className="pr-4">
                    <span className="text-muted">{i.components} component{i.components === 1 ? "" : "s"}, {i.tiers} tier{i.tiers === 1 ? "" : "s"}.</span> {i.summary}
                    {i.warnings.map((w) => <p key={w} className="mt-1 text-xs text-warning">{w}</p>)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
