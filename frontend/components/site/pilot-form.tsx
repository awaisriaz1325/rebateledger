"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, Checkbox, Field, Input, Notice, Select, Textarea, describedBy } from "@/components/ui/core";
import { api, unwrap } from "@/lib/api";
import { applyServerErrors, zodResolver } from "@/lib/forms";

/** Mirrors (does not replace) the server's PilotIn validation. */
const schema = z.object({
  name: z.string().trim().min(1, "Enter your name.").max(200),
  email: z.string().trim().email("Enter a valid work email."),
  company: z.string().trim().min(1, "Enter your company.").max(200),
  role: z.string().max(100),
  segment: z.string().max(60),
  erp_system: z.string().max(100),
  supplier_count: z.string().max(40),
  message: z.string().max(2000, "Keep it under 2,000 characters."),
  consent: z.literal(true, { message: "Please agree so we can contact you." }),
  website: z.string().max(200),
});
type Values = z.infer<typeof schema>;
const FIELDS = ["name", "email", "company", "role", "segment", "erp_system", "supplier_count", "message", "consent"] as const;

const SEGMENTS = ["Electrical", "Plumbing / HVAC", "Industrial / MRO", "Building materials", "Foodservice", "Janitorial / packaging", "Other"];

export function PilotForm() {
  const params = useSearchParams();
  const plan = params.get("plan");
  const [sent, setSent] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", email: "", company: "", role: "", segment: "", erp_system: "", supplier_count: "", message: plan ? `Interested in the ${plan} plan.` : "", website: "" },
  });
  const { errors, isSubmitting } = form.formState;
  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      unwrap(await api.POST("/api/v1/pilot-requests", { body: values }));
      setSent(true);
    } catch (e) {
      setFormError(applyServerErrors(e, form.setError, FIELDS));
    }
  });
  if (sent) {
    return (
      <Notice tone="positive" title="Thanks — your request is in">
        We sent a confirmation to your email and will reply within two business days.
      </Notice>
    );
  }
  const err = (k: keyof Values) => errors[k]?.message as string | undefined;
  return (
    <form onSubmit={onSubmit} noValidate className="grid max-w-3xl grid-cols-1 gap-4 sm:grid-cols-2" aria-label="Request a pilot">
      {formError ? <div className="sm:col-span-2"><Notice tone="negative">{formError}</Notice></div> : null}
      <Field id="name" label="Your name" required error={err("name")}><Input id="name" autoComplete="name" aria-invalid={!!errors.name} aria-describedby={describedBy("name", err("name"))} {...form.register("name")} /></Field>
      <Field id="email" label="Work email" required error={err("email")}><Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} aria-describedby={describedBy("email", err("email"))} {...form.register("email")} /></Field>
      <Field id="company" label="Company" required error={err("company")}><Input id="company" autoComplete="organization" aria-invalid={!!errors.company} {...form.register("company")} /></Field>
      <Field id="role" label="Your role" error={err("role")}><Input id="role" autoComplete="organization-title" {...form.register("role")} /></Field>
      <Field id="segment" label="Distributor segment">
        <Select id="segment" {...form.register("segment")}>
          <option value="">Choose…</option>
          {SEGMENTS.map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
      </Field>
      <Field id="erp_system" label="ERP / accounting system" hint="e.g. Epicor Eclipse, Infor SX.e, NetSuite"><Input id="erp_system" {...form.register("erp_system")} /></Field>
      <Field id="supplier_count" label="Approximate number of supplier rebate agreements">
        <Select id="supplier_count" {...form.register("supplier_count")}>
          <option value="">Choose…</option>
          {["1-10", "11-25", "26-50", "51-100", "100+"].map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
      </Field>
      <Field id="message" label="Anything we should know?" className="sm:col-span-2" error={err("message")}><Textarea id="message" rows={4} {...form.register("message")} /></Field>
      {/* Honeypot: hidden from people and assistive tech; bots tend to fill it. */}
      <div aria-hidden="true" className="hidden">
        <label htmlFor="website">Website</label>
        <input id="website" tabIndex={-1} autoComplete="off" {...form.register("website")} />
      </div>
      <div className="sm:col-span-2">
        <Checkbox id="consent" label="I agree to be contacted about a pilot. We use these details only to reply to you." aria-invalid={!!errors.consent} {...form.register("consent")} />
        {err("consent") ? <p className="mt-1 text-sm text-negative" id="consent-error">{err("consent")}</p> : null}
      </div>
      <div className="sm:col-span-2"><Button type="submit" loading={isSubmitting}>Send request</Button></div>
    </form>
  );
}
