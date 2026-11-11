import Link from "next/link";
import type { ReactNode } from "react";
import { PRODUCT_NAME } from "@/lib/site";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="px-6 py-5">
        <Link href="/" className="inline-flex items-center gap-2 text-base font-semibold text-ink">
          <span aria-hidden="true" className="inline-block h-5 w-5 rounded-sm bg-brand" />
          {PRODUCT_NAME}
        </Link>
      </header>
      <main id="main" className="flex flex-1 items-start justify-center px-4 pt-8 pb-16 sm:pt-16">
        <div className="w-full max-w-md rounded-lg border border-rule bg-surface p-8 shadow-card">{children}</div>
      </main>
    </div>
  );
}
