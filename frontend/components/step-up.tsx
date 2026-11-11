"use client";

import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Button, Field, Input, Notice } from "@/components/ui/core";
import { Dialog } from "@/components/ui/overlay";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api";
import { useSession } from "@/lib/session";

type Runner = <T>(fn: () => Promise<T>) => Promise<T>;
const StepUpContext = createContext<Runner | null>(null);

/**
 * Runs sensitive actions; when the API answers STEP_UP_REQUIRED the user confirms
 * their password (and authenticator code), then the action is retried once (SPEC §4.1).
 */
export function StepUpProvider({ children }: { children: ReactNode }) {
  const session = useSession();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ resolve: () => void; reject: (e: unknown) => void } | null>(null);

  const run = useCallback<Runner>(async (fn) => {
    try {
      return await fn();
    } catch (e) {
      if (!(e instanceof ApiError) || e.code !== "STEP_UP_REQUIRED") throw e;
      await new Promise<void>((resolve, reject) => {
        pending.current = { resolve, reject };
        setError(null);
        setPassword("");
        setCode("");
        setOpen(true);
      });
      return fn();
    }
  }, []);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      unwrap(await api.POST("/api/v1/auth/step-up", { body: { password, code: session.user?.mfa_enabled ? code : null } }));
      setOpen(false);
      pending.current?.resolve();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <StepUpContext.Provider value={run}>
      {children}
      <Dialog
        open={open}
        onOpenChange={(o) => {
          if (!o) pending.current?.reject(new ApiError({ title: "Cancelled", status: 499, code: "STEP_UP_CANCELLED", detail: "Confirmation was cancelled." }));
          setOpen(o);
        }}
        title="Confirm it's you"
        description="This change needs your password again (valid for 10 minutes)."
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => void confirm()} loading={busy} disabled={!password}>Confirm</Button>
          </>
        }
      >
        <form className="flex flex-col gap-4" onSubmit={(e) => { e.preventDefault(); void confirm(); }}>
          {error ? <Notice tone="negative">{error}</Notice> : null}
          <Field id="stepup-password" label="Password">
            <Input id="stepup-password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
          </Field>
          {session.user?.mfa_enabled ? (
            <Field id="stepup-code" label="Authenticator code">
              <Input id="stepup-code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
          ) : null}
          <button type="submit" hidden />
        </form>
      </Dialog>
    </StepUpContext.Provider>
  );
}

export function useStepUp(): Runner {
  const run = useContext(StepUpContext);
  if (!run) throw new Error("useStepUp needs StepUpProvider");
  return run;
}
