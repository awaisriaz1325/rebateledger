"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";
import { Button, Card, Checkbox, Field, Notice, PageHeader } from "@/components/ui/core";
import { PermissionDenied } from "@/components/ui/states";
import { ApiError, idempotencyKey, uploadForm } from "@/lib/api";
import { can, useSession } from "@/lib/session";
import type { Batch } from "@/lib/types";

const TYPES = [
  { value: "purchases", label: "Purchase lines", help: "Invoice lines from your ERP: supplier code, invoice, SKU, quantity, amount, dates." },
  { value: "credits", label: "Supplier credits", help: "Rebate credit memos: supplier code, reference, date, amount." },
  { value: "baselines", label: "Baselines", help: "Baseline measures for growth agreements, per agreement and period." },
  { value: "products", label: "Product catalog", help: "SKU to category mapping." },
  { value: "suppliers", label: "Suppliers", help: "Bulk-create suppliers and their codes." },
  { value: "sales", label: "Sales lines (SPA claims)", help: "What you sold under special pricing: supplier code, invoice, date, customer, job, SKU, quantity, cost." },
] as const;

export default function NewImportPage() {
  return (
    <Suspense>
      <Upload />
    </Suspense>
  );
}

/** Step 1 of the wizard: choose the type and upload. The remaining steps live on the import page. */
function Upload() {
  const session = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const initial = TYPES.find((t) => t.value === params.get("type"))?.value ?? "purchases";
  const [type, setType] = useState<(typeof TYPES)[number]["value"]>(initial);
  const [file, setFile] = useState<File | null>(null);
  const [duplicate, setDuplicate] = useState<{ previous: string; when: string } | null>(null);
  const [confirmDup, setConfirmDup] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!can(session, "manage_imports")) return <PermissionDenied />;

  async function submit() {
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("import_type", type);
      form.append("confirm_duplicate", confirmDup ? "true" : "false");
      const batch = await uploadForm<Batch>("/api/v1/imports", form, { "Idempotency-Key": idempotencyKey() });
      router.push(`/app/imports/${batch.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.code === "FILE_ALREADY_IMPORTED") {
        setDuplicate({ previous: String(e.problem.previous_batch_id), when: String(e.problem.previous_uploaded_at).slice(0, 10) });
      } else {
        toast.error(e instanceof ApiError ? e.problem.detail || e.problem.title : "Upload failed");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="New import" description="Step 1 of 5 — choose what you are importing and upload the file. Nothing is saved to your data until you commit." />
      <Card>
        <form className="flex max-w-2xl flex-col gap-5" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          <fieldset>
            <legend className="mb-2 text-[13px] font-medium">What are you importing?</legend>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {TYPES.map((t) => (
                <label key={t.value} className={`flex cursor-pointer flex-col rounded-md border p-3 text-sm ${type === t.value ? "border-brand bg-brand-soft" : "border-rule hover:bg-surface-2"}`}>
                  <span className="flex items-center gap-2 font-medium"><input type="radio" name="type" value={t.value} checked={type === t.value} onChange={() => setType(t.value)} />{t.label}</span>
                  <span className="mt-1 text-xs text-muted">{t.help}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <Field id="file" label="File" hint="CSV or XLSX, up to 50 MB and 1,000,000 rows. Macro-enabled workbooks are not accepted.">
            <input id="file" type="file" accept=".csv,.txt,.xlsx" className="text-sm" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setDuplicate(null); setConfirmDup(false); }} />
          </Field>
          {duplicate ? (
            <Notice tone="warning" title="This exact file was uploaded before">
              <p>An identical file was uploaded on {duplicate.when}. Importing it again usually creates no new rows (duplicates are skipped), but check you meant to.</p>
              <div className="mt-2"><Checkbox id="confirm-dup" label="Upload it again anyway" checked={confirmDup} onChange={(e) => setConfirmDup(e.target.checked)} /></div>
              <a className="mt-2 inline-block text-sm text-brand underline" href={`/app/imports/${duplicate.previous}`}>Open the earlier import</a>
            </Notice>
          ) : null}
          <div><Button type="submit" loading={busy} disabled={!file || (duplicate !== null && !confirmDup)}>Upload and continue</Button></div>
        </form>
      </Card>
    </>
  );
}
