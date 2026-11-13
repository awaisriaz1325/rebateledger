import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";

// "Dashboard" is the title of /app itself; every child segment sets its own (see their layout.tsx).
export const metadata: Metadata = { title: "Dashboard", robots: { index: false, follow: false } };

export default function AppLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
