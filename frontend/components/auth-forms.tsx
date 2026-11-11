"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, Field, Input, Notice, describedBy } from "@/components/ui/core";
import { api, errorMessage, unwrap } from "@/lib/api";
import { applyServerErrors, useLinkToken, zodResolver } from "@/lib/forms";
import { useRefreshSession } from "@/lib/session";

export const PASSWORD_HINT = "At least 12 characters. A long passphrase works well; common or breached passwords are refused.";
const password = z.string().min(12, "Use at least 12 characters.").max(128, "Use at most 128 characters.");

export function ForgotPasswordForm() {
  const [sent, setSent] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<{ email: string }>({ resolver: zodResolver(z.object({ email: z.string().trim().email("Enter a valid email address.") })) });
  const onSubmit = form.handleSubmit(async (body) => {
    setFormError(null);
    try {
      unwrap(await api.POST("/api/v1/auth/password/forgot", { body }));
      setSent(true);
    } catch (e) {
      setFormError(applyServerErrors(e, form.setError, ["email"]));
    }
  });
  if (sent) {
    return (
      <>
        <h1 className="text-xl font-semibold">Check your email</h1>
        <p className="mt-2 text-sm text-muted">If an account exists for that address, a reset link is on its way. It expires in 30 minutes and works once.</p>
        <p className="mt-6 text-sm"><Link href="/login" className="text-brand hover:underline">Back to sign in</Link></p>
      </>
    );
  }
  const { errors, isSubmitting } = form.formState;
  return (
    <>
      <h1 className="text-xl font-semibold">Reset your password</h1>
      <p className="mt-1 mb-6 text-sm text-muted">We’ll email you a link to choose a new password.</p>
      {formError ? <div className="mb-4"><Notice tone="negative">{formError}</Notice></div> : null}
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Field id="email" label="Email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} aria-describedby={describedBy("email", errors.email?.message)} {...form.register("email")} />
        </Field>
        <Button type="submit" loading={isSubmitting}>Send reset link</Button>
      </form>
      <p className="mt-6 text-sm"><Link href="/login" className="text-brand hover:underline">Back to sign in</Link></p>
    </>
  );
}

function MissingToken() {
  return <Notice tone="negative" title="This link is incomplete">Open the link from your email again, or request a new one.</Notice>;
}

export function ResetPasswordForm() {
  const token = useLinkToken();
  const [done, setDone] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const schema = z.object({ password, confirm: z.string() }).refine((v) => v.password === v.confirm, { message: "The passwords do not match.", path: ["confirm"] });
  const form = useForm<{ password: string; confirm: string }>({ resolver: zodResolver(schema) });
  const onSubmit = form.handleSubmit(async ({ password: pw }) => {
    setFormError(null);
    try {
      unwrap(await api.POST("/api/v1/auth/password/reset", { body: { token: token ?? "", password: pw } }));
      setDone(true);
    } catch (e) {
      setFormError(applyServerErrors(e, form.setError, ["password"]));
    }
  });
  if (!token) return <MissingToken />;
  if (done) {
    return (
      <>
        <h1 className="text-xl font-semibold">Password changed</h1>
        <p className="mt-2 text-sm text-muted">All sessions were signed out. Sign in with your new password.</p>
        <Link href="/login" className="mt-6 inline-flex h-9 items-center rounded-md bg-brand px-4 text-sm font-medium text-on-brand">Sign in</Link>
      </>
    );
  }
  const { errors, isSubmitting } = form.formState;
  return (
    <>
      <h1 className="text-xl font-semibold">Choose a new password</h1>
      {formError ? <div className="my-4"><Notice tone="negative">{formError}</Notice></div> : null}
      <form onSubmit={onSubmit} noValidate className="mt-6 flex flex-col gap-4">
        <Field id="password" label="New password" hint={PASSWORD_HINT} error={errors.password?.message}>
          <Input id="password" type="password" autoComplete="new-password" aria-invalid={!!errors.password} aria-describedby={describedBy("password", errors.password?.message, PASSWORD_HINT)} {...form.register("password")} />
        </Field>
        <Field id="confirm" label="Repeat new password" error={errors.confirm?.message}>
          <Input id="confirm" type="password" autoComplete="new-password" aria-invalid={!!errors.confirm} aria-describedby={describedBy("confirm", errors.confirm?.message)} {...form.register("confirm")} />
        </Field>
        <Button type="submit" loading={isSubmitting}>Change password</Button>
      </form>
    </>
  );
}

/** One-click token links: verify email, confirm email change, unsubscribe. */
export function TokenAction({ kind }: { kind: "verify" | "change-email" | "unsubscribe" }) {
  const token = useLinkToken();
  const [state, setState] = useState<"working" | "done" | "error">("working");
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (!token) return;
    void (async () => {
      try {
        if (kind === "verify") unwrap(await api.POST("/api/v1/auth/email/verify", { body: { token } }));
        else if (kind === "change-email") unwrap(await api.POST("/api/v1/auth/email/confirm-change", { body: { token } }));
        else {
          const out = unwrap(await api.POST("/api/v1/unsubscribe", { body: { token } }));
          setMessage(`You will no longer receive “${out.unsubscribed_from}” emails. Change this any time in Settings → Notifications.`);
        }
        setState("done");
      } catch (e) {
        setMessage(errorMessage(e));
        setState("error");
      }
    })();
  }, [token, kind]);
  if (!token) return <MissingToken />;
  const titles = { verify: "Email confirmed", "change-email": "Email address changed", unsubscribe: "Unsubscribed" };
  if (state === "working") return <p role="status">Working…</p>;
  if (state === "error") return <Notice tone="negative" title="This link did not work">{message}</Notice>;
  return (
    <>
      <h1 className="text-xl font-semibold">{titles[kind]}</h1>
      <p className="mt-2 text-sm text-muted">
        {kind === "change-email" ? "Sign in with your new email address. Your old address was notified." : message || "Thanks — you're all set."}
      </p>
      <Link href={kind === "unsubscribe" ? "/" : "/login"} className="mt-6 inline-flex text-sm text-brand hover:underline">
        {kind === "unsubscribe" ? "Go to the website" : "Continue to sign in"}
      </Link>
    </>
  );
}

export function AcceptInviteForm() {
  const token = useLinkToken();
  const router = useRouter();
  const refresh = useRefreshSession();
  const [preview, setPreview] = useState<{ organization_name: string; email: string; role: string; has_account: boolean } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  useEffect(() => {
    if (!token) return;
    void (async () => {
      try {
        setPreview(unwrap(await api.POST("/api/v1/auth/invites/preview", { body: { token } })));
      } catch (e) {
        setLoadError(errorMessage(e));
      }
    })();
  }, [token]);
  const schema = preview?.has_account ? z.object({ name: z.string().optional(), password: z.string().min(1, "Enter your password.") }) : z.object({ name: z.string().trim().min(1, "Enter your name.").max(200), password });
  const form = useForm<{ name?: string; password: string }>({ resolver: zodResolver(schema) });
  const onSubmit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      const session = unwrap(await api.POST("/api/v1/auth/invites/accept", { body: { token: token ?? "", password: values.password, name: preview?.has_account ? null : values.name } }));
      await refresh(session);
      router.push(session.state === "pending_enrollment" ? "/mfa/setup?next=/app" : session.state === "pending_mfa" ? "/login" : "/app");
    } catch (e) {
      setFormError(applyServerErrors(e, form.setError, ["name", "password"]));
    }
  });
  if (!token) return <MissingToken />;
  if (loadError) return <Notice tone="negative" title="This invitation can't be used">{loadError}</Notice>;
  if (!preview) return <p role="status">Checking your invitation…</p>;
  const { errors, isSubmitting } = form.formState;
  return (
    <>
      <h1 className="text-xl font-semibold">Join {preview.organization_name}</h1>
      <p className="mt-1 mb-6 text-sm text-muted">
        You’re invited as <strong className="capitalize">{preview.role}</strong> with {preview.email}.{" "}
        {preview.has_account ? "Confirm with the password of your existing account." : "Set up your account to accept."}
      </p>
      {formError ? <div className="mb-4"><Notice tone="negative">{formError}</Notice></div> : null}
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        {!preview.has_account ? (
          <Field id="name" label="Your name" error={errors.name?.message}>
            <Input id="name" autoComplete="name" aria-invalid={!!errors.name} aria-describedby={describedBy("name", errors.name?.message)} {...form.register("name")} />
          </Field>
        ) : null}
        <Field id="password" label={preview.has_account ? "Password" : "Choose a password"} hint={preview.has_account ? undefined : PASSWORD_HINT} error={errors.password?.message}>
          <Input id="password" type="password" autoComplete={preview.has_account ? "current-password" : "new-password"} aria-invalid={!!errors.password} aria-describedby={describedBy("password", errors.password?.message, preview.has_account ? undefined : PASSWORD_HINT)} {...form.register("password")} />
        </Field>
        <Button type="submit" loading={isSubmitting}>Accept invitation</Button>
      </form>
    </>
  );
}
