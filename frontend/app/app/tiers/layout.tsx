import type { Metadata } from "next";
import type { ReactNode } from "react";

/** Page title (WCAG 2.4.2): the client page cannot export metadata, so this layout does. */
export const metadata: Metadata = { title: "Tier tracker" };

export default function Layout({ children }: { children: ReactNode }) {
  return children;
}
