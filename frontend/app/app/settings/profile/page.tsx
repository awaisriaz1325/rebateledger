"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { PASSWORD_HINT } from "@/components/auth-forms";
import { useStepUp } from "@/components/step-up";
import { Button, Card, Field, Input, Notice, describedBy } from "@/components/ui/core";
import { ConfirmDialog } from "@/components/ui/overlay";
import { QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { applyServerErrors, zodResolver } from "@/lib/forms";
import { useRefreshSession, useSession } from "@/lib/session";

export default function ProfilePage() {
  return (
    <div className="flex flex-col gap-6">
      <NameCard />
      <PasswordCard />
      <EmailCard />
      <MfaCard />
      <SessionsCard />
    </div>
  );
}

function NameCard() {
  const session = useSession();
  const refresh = useRefreshSession();
  const form = useForm<{ name: string }>({ defaultValues: { name: session.user?.name ?? "" }, resolver: zodResolver(z.object({ name: z.string().trim().min(1, "Enter your name.").max(200) })) });
  const onSubmit = form.handleSubmit(async (body) => {
    try {
      unwrap(await api.PATCH("/api/v1/me", { body }));
      await refresh();
      toast.success("Name saved");
    } catch (e) {
      toast.error(applyServerErrors(e, form.setError, ["name"]) ?? "Could not save");
    }
  });
  const err = form.formState.errors.name?.message;
  return (
    <Card title="Profile">
      <form onSubmit={onSubmit} noValidate className="flex max-w-md flex-col gap-4">
        <Field id="name" label="Name" error={err}>
          <Input id="name" autoComplete="name" aria-invalid={!!err} aria-describedby={describedBy("name", err)} {...form.register("name")} />
        </Field>
        <p className="text-sm text-muted">Email: {session.user?.email} {session.user?.email_verified ? "" : "(not verified)"}</p>
        <div><Button type="submit" loading={form.formState.isSubmitting}>Save</Button></div>
      </form>
    </Card>
  );
}

function PasswordCard() {
  const schema = z
    .object({ current_password: z.string().min(1, "Enter your current password."), new_password: z.string().min(12, "Use at least 12 characters.").max(128), confirm: z.string() })
    .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "The passwords do not match." });
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  const onSubmit = form.handleSubmit(async ({ current_password, new_password }) => {
    try {
      unwrap(await api.POST("/api/v1/me/password", { body: { current_password, new_password } }));
      form.reset();
      toast.success("Password changed. Your other sessions were signed out.");
    } catch (e) {
      const msg = applyServerErrors(e, form.setError, ["current_password", "new_password"]);
      if (msg) toast.error(msg);
    }
  });
  const e = form.formState.errors;
  return (
    <Card title="Password">
      <form onSubmit={onSubmit} noValidate className="flex max-w-md flex-col gap-4">
        <Field id="current_password" label="Current password" error={e.current_password?.message}>
          <Input id="current_password" type="password" autoComplete="current-password" aria-invalid={!!e.current_password} aria-describedby={describedBy("current_password", e.current_password?.message)} {...form.register("current_password")} />
        </Field>
        <Field id="new_password" label="New password" hint={PASSWORD_HINT} error={e.new_password?.message}>
          <Input id="new_password" type="password" autoComplete="new-password" aria-invalid={!!e.new_password} aria-describedby={describedBy("new_password", e.new_password?.message, PASSWORD_HINT)} {...form.register("new_password")} />
        </Field>
        <Field id="confirm" label="Repeat new password" error={e.confirm?.message}>
          <Input id="confirm" type="password" autoComplete="new-password" aria-invalid={!!e.confirm} aria-describedby={describedBy("confirm", e.confirm?.message)} {...form.register("confirm")} />
        </Field>
        <div><Button type="submit" loading={form.formState.isSubmitting}>Change password</Button></div>
      </form>
    </Card>
  );
}

function EmailCard() {
  const [sent, setSent] = useState<string | null>(null);
  const schema = z.object({ new_email: z.string().trim().email("Enter a valid email address."), password: z.string().min(1, "Enter your password.") });
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  const onSubmit = form.handleSubmit(async (body) => {
    try {
      unwrap(await api.POST("/api/v1/me/email", { body }));
      setSent(body.new_email);
      form.reset();
    } catch (e) {
      const msg = applyServerErrors(e, form.setError, ["new_email", "password"]);
      if (msg) toast.error(msg);
    }
  });
  const e = form.formState.errors;
  return (
    <Card title="Sign-in email">
      {sent ? <div className="mb-4"><Notice tone="positive">Check {sent} for a confirmation link. Your current address stays active until you confirm.</Notice></div> : null}
      <form onSubmit={onSubmit} noValidate className="flex max-w-md flex-col gap-4">
        <Field id="new_email" label="New email" error={e.new_email?.message}>
          <Input id="new_email" type="email" autoComplete="email" aria-invalid={!!e.new_email} aria-describedby={describedBy("new_email", e.new_email?.message)} {...form.register("new_email")} />
        </Field>
        <Field id="email_password" label="Password" error={e.password?.message}>
          <Input id="email_password" type="password" autoComplete="current-password" aria-invalid={!!e.password} aria-describedby={describedBy("email_password", e.password?.message)} {...form.register("password")} />
        </Field>
        <div><Button type="submit" variant="secondary" loading={form.formState.isSubmitting}>Send confirmation</Button></div>
      </form>
    </Card>
  );
}

function MfaCard() {
  const router = useRouter();
  const session = useSession();
  const stepUp = useStepUp();
  const [codes, setCodes] = useState<string[] | null>(null);
  const [confirmDisable, setConfirmDisable] = useState(false);
  const regenerate = useMutation({
    mutationFn: () => stepUp(async () => unwrap(await api.POST("/api/v1/auth/mfa/recovery-codes"))),
    onSuccess: (out) => setCodes(out.recovery_codes),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const disable = useMutation({
    mutationFn: () => stepUp(async () => unwrap(await api.POST("/api/v1/auth/mfa/disable"))),
    onSuccess: () => router.push("/login"),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const enabled = session.user?.mfa_enabled;
  return (
    <Card title="Two-factor authentication">
      <p className="mb-4 text-sm">
        Status: <strong>{enabled ? "On" : "Off"}</strong>
        {session.mfa_required ? <span className="text-muted"> — required for your role or organization</span> : null}
      </p>
      {session.user?.must_reenroll_mfa ? <div className="mb-4"><Notice tone="warning">You signed in with a recovery code. Set up your authenticator again.</Notice></div> : null}
      {codes ? (
        <div className="mb-4">
          <Notice tone="positive" title="New recovery codes">Your old codes no longer work.</Notice>
          <ul className="mt-3 grid max-w-md grid-cols-2 gap-2 rounded-md border border-rule bg-surface-2 p-4 font-mono text-sm">{codes.map((c) => <li key={c}>{c}</li>)}</ul>
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {!enabled || session.user?.must_reenroll_mfa ? (
          <a href="/mfa/setup?next=/app/settings/profile" className="inline-flex h-9 items-center rounded-md bg-brand px-4 text-sm font-medium text-on-brand">Set up authenticator</a>
        ) : (
          <Button variant="secondary" onClick={() => regenerate.mutate()} loading={regenerate.isPending}>Create new recovery codes</Button>
        )}
        {enabled && !session.mfa_required ? <Button variant="danger" onClick={() => setConfirmDisable(true)}>Turn off</Button> : null}
      </div>
      <ConfirmDialog
        open={confirmDisable}
        onOpenChange={setConfirmDisable}
        title="Turn off two-factor authentication?"
        description="Your account will be protected by your password only, and all sessions will be signed out."
        confirmLabel="Turn off"
        pending={disable.isPending}
        onConfirm={() => disable.mutate()}
      />
    </Card>
  );
}

function SessionsCard() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["me", "sessions"], queryFn: async () => unwrap(await api.GET("/api/v1/me/sessions")) });
  const revoke = useMutation({
    mutationFn: async (id: string) => unwrap(await api.DELETE("/api/v1/me/sessions/{session_id}", { params: { path: { session_id: id } } })),
    onSuccess: () => {
      toast.success("Session signed out");
      void qc.invalidateQueries({ queryKey: ["me", "sessions"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Active sessions">
      <QueryState query={query}>
        {(sessions) => (
          <ul className="divide-y divide-rule" aria-label="Active sessions">
            {sessions.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{s.user_agent || "Unknown browser"}</p>
                  <p className="text-xs text-muted">Signed in {formatDateTime(s.created_at)} · last active {formatDateTime(s.last_seen_at)}</p>
                </div>
                {s.current ? (
                  <span className="text-xs font-medium text-positive">This device</span>
                ) : (
                  <Button variant="secondary" size="sm" loading={revoke.isPending && revoke.variables === s.id} onClick={() => revoke.mutate(s.id)}>Sign out</Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </Card>
  );
}
