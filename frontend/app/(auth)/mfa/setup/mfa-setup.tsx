"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, Checkbox, Field, Input, Notice, describedBy } from "@/components/ui/core";
import { api, errorMessage, unwrap } from "@/lib/api";
import { applyServerErrors, safeNext, zodResolver } from "@/lib/forms";
import { useRefreshSession } from "@/lib/session";

const schema = z.object({ code: z.string().trim().regex(/^\d{6}$/, "Enter the 6-digit code.") });

export function MfaSetup() {
  const router = useRouter();
  const params = useSearchParams();
  const refresh = useRefreshSession();
  const setup = useMutation({ mutationFn: async () => unwrap(await api.POST("/api/v1/auth/mfa/setup")) });
  const [codes, setCodes] = useState<string[] | null>(null);
  const [saved, setSaved] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const form = useForm<{ code: string }>({ resolver: zodResolver(schema) });
  const { mutate } = setup;
  useEffect(() => mutate(), [mutate]);

  const onSubmit = form.handleSubmit(async ({ code }) => {
    setFormError(null);
    try {
      const out = unwrap(await api.POST("/api/v1/auth/mfa/confirm", { body: { code } }));
      setCodes(out.recovery_codes);
    } catch (e) {
      setFormError(applyServerErrors(e, form.setError, ["code"]));
    }
  });

  if (codes) {
    return (
      <>
        <h1 className="text-xl font-semibold">Save your recovery codes</h1>
        <p className="mt-1 mb-4 text-sm text-muted">
          If you lose your phone, each code signs you in once. Store them somewhere safe; they will not be shown again.
        </p>
        <ul className="mb-4 grid grid-cols-2 gap-2 rounded-md border border-rule bg-surface-2 p-4 font-mono text-sm" aria-label="Recovery codes">
          {codes.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <div className="mb-4 flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={() => downloadCodes(codes)}>
            Download as text file
          </Button>
          <Button variant="secondary" size="sm" onClick={() => void navigator.clipboard.writeText(codes.join("\n"))}>
            Copy
          </Button>
        </div>
        <Checkbox id="saved" label="I have saved these codes" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        <Button
          className="mt-6 w-full"
          disabled={!saved}
          onClick={async () => {
            await refresh();
            router.push(safeNext(params.get("next")));
          }}
        >
          Continue
        </Button>
      </>
    );
  }

  const { errors, isSubmitting } = form.formState;
  return (
    <>
      <h1 className="text-xl font-semibold">Set up two-factor authentication</h1>
      <p className="mt-1 mb-6 text-sm text-muted">
        Your role requires it. Scan the code with an authenticator app (for example 1Password, Google Authenticator or Microsoft Authenticator), then enter the 6-digit code it shows.
      </p>
      {setup.isError ? <Notice tone="negative">{errorMessage(setup.error)}</Notice> : null}
      {setup.data ? (
        <div className="mb-6 flex flex-col items-center gap-3">
          <div className="rounded-md bg-white p-3">
            <QRCodeSVG value={setup.data.otpauth_uri} size={176} title="QR code for your authenticator app" />
          </div>
          <details className="w-full text-sm">
            <summary className="cursor-pointer text-brand">Can’t scan? Enter the key manually</summary>
            <p className="mt-2 font-mono text-sm break-all select-all">{setup.data.secret}</p>
          </details>
        </div>
      ) : (
        <div className="skeleton mx-auto mb-6 h-44 w-44" aria-hidden="true" />
      )}
      {formError ? <div className="mb-4"><Notice tone="negative">{formError}</Notice></div> : null}
      <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
        <Field id="code" label="6-digit code" error={errors.code?.message}>
          <Input id="code" inputMode="numeric" autoComplete="one-time-code" aria-invalid={!!errors.code} aria-describedby={describedBy("code", errors.code?.message)} {...form.register("code")} />
        </Field>
        <Button type="submit" loading={isSubmitting} disabled={!setup.data}>
          Turn on two-factor authentication
        </Button>
      </form>
    </>
  );
}

function downloadCodes(codes: string[]) {
  const text = `RebateLedger recovery codes\nEach code works once.\n\n${codes.join("\n")}\n`;
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "rebateledger-recovery-codes.txt";
  a.click();
  URL.revokeObjectURL(url);
}
