"use client";

import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, Field, Input, Notice, Select, Textarea, describedBy } from "@/components/ui/core";
import { applyServerErrors, zodResolver } from "@/lib/forms";
import { useState } from "react";

const schema = z.object({
  name: z.string().trim().min(1, "Enter the supplier's name.").max(200),
  codes: z.string().trim().min(1, "Add at least one code."),
  category_tags: z.string().max(500),
  payment_notes: z.string().max(2000),
  notes: z.string().max(5000),
});
export type SupplierValues = z.infer<typeof schema>;
export type SupplierKind = "supplier" | "buying_group";
export type SupplierPayload = { name: string; codes: string[]; category_tags: string[]; payment_notes: string; notes: string; kind?: SupplierKind };

const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

/** ``chooseKind``: only when creating; the type of an existing record cannot change. */
export function SupplierForm({ initial, submitLabel, onSubmit, chooseKind = false }: { initial?: Partial<SupplierValues>; submitLabel: string; onSubmit: (v: SupplierPayload) => Promise<void>; chooseKind?: boolean }) {
  const [formError, setFormError] = useState<string | null>(null);
  const [kind, setKind] = useState<SupplierKind>("supplier");
  const form = useForm<SupplierValues>({ resolver: zodResolver(schema), defaultValues: { name: "", codes: "", category_tags: "", payment_notes: "", notes: "", ...initial } });
  const submit = form.handleSubmit(async (v) => {
    setFormError(null);
    try {
      await onSubmit({ name: v.name, codes: split(v.codes), category_tags: split(v.category_tags), payment_notes: v.payment_notes, notes: v.notes, ...(chooseKind ? { kind } : {}) });
    } catch (e) {
      setFormError(applyServerErrors(e, form.setError, ["name", "codes", "category_tags", "payment_notes", "notes"]));
    }
  });
  const e = form.formState.errors;
  return (
    <form onSubmit={submit} noValidate className="flex max-w-2xl flex-col gap-4">
      {formError ? <Notice tone="negative">{formError}</Notice> : null}
      {chooseKind ? (
        <Field id="kind" label="Type" hint={kind === "buying_group" ? "A buying group pays rebates on purchases from its member suppliers. Add members after saving; never import purchases under the group's code." : "A company you buy from."}>
          <Select id="kind" value={kind} onChange={(ev) => setKind(ev.target.value as SupplierKind)}>
            <option value="supplier">Supplier</option>
            <option value="buying_group">Buying group</option>
          </Select>
        </Field>
      ) : null}
      <Field id="name" label="Name" required error={e.name?.message}>
        <Input id="name" aria-invalid={!!e.name} aria-describedby={describedBy("name", e.name?.message)} {...form.register("name")} />
      </Field>
      <Field id="codes" label="Supplier codes" required hint="Comma-separated, exactly as they appear in your purchase and credit files (e.g. ACME, ACME-01)." error={e.codes?.message}>
        <Input id="codes" className="font-mono" aria-invalid={!!e.codes} aria-describedby={describedBy("codes", e.codes?.message, "x")} {...form.register("codes")} />
      </Field>
      <Field id="category_tags" label="Category tags" hint="Comma-separated, optional.">
        <Input id="category_tags" {...form.register("category_tags")} />
      </Field>
      <Field id="payment_notes" label="Payment notes"><Textarea id="payment_notes" {...form.register("payment_notes")} /></Field>
      <Field id="notes" label="Notes"><Textarea id="notes" {...form.register("notes")} /></Field>
      <div><Button type="submit" loading={form.formState.isSubmitting}>{submitLabel}</Button></div>
    </form>
  );
}
