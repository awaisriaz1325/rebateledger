"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, Field, Input, Notice, describedBy } from "@/components/ui/core";
import { api, unwrap } from "@/lib/api";
import { applyServerErrors, safeNext, zodResolver } from "@/lib/forms";
import { useRefreshSession, type SessionInfo } from "@/lib/session";

const credentials = z.object({
  email: z.string().trim().email("Enter a valid email address."),
  password: z.string().min(1, "Enter your password."),
});
type Credentials = z.infer<typeof credentials>;

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const refresh = useRefreshSession();
  const [step, setStep] = useState<"password" | "mfa">("password");
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<Credentials>({ resolver: zodResolver(credentials) });

  function route(session: SessionInfo) {
    const next = safeNext(params.get("next"));
    if (session.state === "pending_mfa") setStep("mfa");
    else if (session.state === "pending_enrollment") router.push(`/mfa/setup?next=${encodeURIComponent(next)}`);
    else if (session.is_platform_admin && !session.organization) router.push("/ops");
    else router.push(next);
  }

  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      const session = unwrap(await api.POST("/api/v1/auth/login", { body: values }));
      await refresh(session);
      route(session);
    } catch (e) {
      setFormError(applyServerErrors(e, form.setError, ["email", "password"]));
    }
  });

  if (step === "mfa") return <MfaStep onDone={route} />;

  const { errors, isSubmitting } = form.formState;
  return (
    <>
      <h1 className="text-xl font-semibold">Sign in</h1>
      <p className="mt-1 mb-6 text-sm text-muted">Use your work email and password.</p>
      {formError ? <div className="mb-4"><Notice tone="negative">{formError}</Notice></div> : null}
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Field id="email" label="Email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="username" aria-invalid={!!errors.email} aria-describedby={describedBy("email", errors.email?.message)} {...form.register("email")} />
        </Field>
        <Field id="password" label="Password" error={errors.password?.message}>
          <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password} aria-describedby={describedBy("password", errors.password?.message)} {...form.register("password")} />
        </Field>
        <Button type="submit" loading={isSubmitting} className="mt-2">
          Sign in
        </Button>
      </form>
      <p className="mt-6 text-sm">
        <Link href="/forgot-password" className="text-brand underline-offset-2 hover:underline">
          Forgot your password?
        </Link>
      </p>
    </>
  );
}

const codeSchema = z.object({ code: z.string().trim().min(6, "Enter the 6-digit code or a recovery code.").max(20) });

function MfaStep({ onDone }: { onDone: (s: SessionInfo) => void }) {
  const refresh = useRefreshSession();
  const [recovery, setRecovery] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<{ code: string }>({ resolver: zodResolver(codeSchema) });
  const onSubmit = form.handleSubmit(async ({ code }) => {
    setFormError(null);
    try {
      const body = recovery ? { recovery_code: code } : { code };
      const session = unwrap(await api.POST("/api/v1/auth/mfa/verify", { body }));
      await refresh(session);
      onDone(session);
    } catch (e) {
      setFormError(applyServerErrors(e, form.setError, ["code"]));
      form.reset();
    }
  });
  const { errors, isSubmitting } = form.formState;
  return (
    <>
      <h1 className="text-xl font-semibold">Two-factor authentication</h1>
      <p className="mt-1 mb-6 text-sm text-muted">
        {recovery ? "Enter one of your recovery codes. Each code works once." : "Enter the 6-digit code from your authenticator app."}
      </p>
      {formError ? <div className="mb-4"><Notice tone="negative">{formError}</Notice></div> : null}
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Field id="code" label={recovery ? "Recovery code" : "Authentication code"} error={errors.code?.message}>
          <Input
            id="code"
            autoFocus
            autoComplete="one-time-code"
            inputMode={recovery ? "text" : "numeric"}
            aria-invalid={!!errors.code}
            aria-describedby={describedBy("code", errors.code?.message)}
            {...form.register("code")}
          />
        </Field>
        <Button type="submit" loading={isSubmitting}>
          Verify
        </Button>
      </form>
      <button type="button" className="mt-6 text-sm text-brand underline-offset-2 hover:underline" onClick={() => setRecovery((r) => !r)}>
        {recovery ? "Use your authenticator app instead" : "Use a recovery code"}
      </button>
    </>
  );
}
