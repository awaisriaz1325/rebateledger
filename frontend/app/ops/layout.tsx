import type { Metadata } from "next";
import type { ReactNode } from "react";
import { OpsShell } from "@/components/shell/ops-shell";

export const metadata: Metadata = { title: "Operations", robots: { index: false, follow: false } };

export default function OpsLayout({ children }: { children: ReactNode }) {
  return <OpsShell>{children}</OpsShell>;
}
