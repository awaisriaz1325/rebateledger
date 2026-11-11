"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { DEFAULT_TERMS, TermsEditor, useTermsValid } from "@/components/terms-editor";
import { Button, Card, Field, Input, Notice, PageHeader, Select, Textarea } from "@/components/ui/core";
import { PermissionDenied } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { fetchAllSuppliers } from "@/lib/queries";
import { can, useSession } from "@/lib/session";
import type { Terms } from "@/lib/types";

export default function NewAgreementPage() {
  const session = useSession();
  const router = useRouter();
  const qc = useQueryClient();
  const suppliers = useQuery({ queryKey: ["suppliers", "all"], queryFn: fetchAllSuppliers });
  const [supplierId, setSupplierId] = useState("");
  const [name, setName] = useState("");
  const [ref, setRef] = useState("");
  const [notes, setNotes] = useState("");
  const [terms, setTerms] = useState<Terms>(DEFAULT_TERMS);
  const valid = useTermsValid(terms);
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/agreements", { body: { supplier_id: supplierId, name, external_reference: ref || null, notes, terms } })),
    onSuccess: (a) => { void qc.invalidateQueries({ queryKey: ["agreements"] }); toast.success("Draft saved"); router.push(`/app/agreements/${a.id}`); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!can(session, "edit_agreements")) return <PermissionDenied />;
  return (
    <>
      <PageHeader title="New agreement" description="Saved as a draft. Activate it when the terms are right." />
      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field id="a-supplier" label="Supplier" required>
            <Select id="a-supplier" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Choose…</option>
              {(suppliers.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
          <Field id="a-name" label="Agreement name" required><Input id="a-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} /></Field>
          <Field id="a-ref" label="Reference on credit memos" hint="Lets credits match this agreement automatically."><Input id="a-ref" className="font-mono" value={ref} onChange={(e) => setRef(e.target.value)} maxLength={100} /></Field>
          <Field id="a-notes" label="Notes" className="sm:col-span-3"><Textarea id="a-notes" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        </div>
        {suppliers.data && suppliers.data.length === 0 ? <div className="mt-4"><Notice tone="warning">Add a supplier first.</Notice></div> : null}
      </Card>
      <TermsEditor value={terms} onChange={setTerms} />
      <div className="mt-6 flex gap-2">
        <Button onClick={() => create.mutate()} loading={create.isPending} disabled={!supplierId || !name.trim() || valid !== true}>Save draft</Button>
        <Button variant="secondary" onClick={() => router.back()}>Cancel</Button>
      </div>
    </>
  );
}
