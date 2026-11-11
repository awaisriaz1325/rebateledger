import type { Metadata } from "next";
import { Suspense } from "react";
import { TokenAction } from "@/components/auth-forms";

export const metadata: Metadata = { title: "Confirm new email", robots: { index: false } };

export default function Page() {
  return (
    <Suspense>
      <TokenAction kind="change-email" />
    </Suspense>
  );
}
