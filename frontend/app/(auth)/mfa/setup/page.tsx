import type { Metadata } from "next";
import { Suspense } from "react";
import { MfaSetup } from "./mfa-setup";

export const metadata: Metadata = { title: "Set up two-factor authentication", robots: { index: false } };

export default function MfaSetupPage() {
  return (
    <Suspense>
      <MfaSetup />
    </Suspense>
  );
}
