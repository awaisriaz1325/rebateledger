"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { UserMenu } from "@/components/shell/user-menu";
import { TableSkeleton } from "@/components/ui/states";
import { SessionProvider, useSessionQuery } from "@/lib/session";
import { PRODUCT_NAME } from "@/lib/site";

const NAV = [
  ["/ops", "Organizations"],
  ["/ops/invoices", "Invoices"],
  ["/ops/plans", "Plans"],
  ["/ops/requests", "Pilot requests"],
  ["/ops/announcements", "Announcements"],
  ["/ops/jobs", "Jobs"],
  ["/ops/settings", "Billing settings"],
  ["/ops/audit", "Operator audit"],
] as const;

/** Operator console shell. The API enforces platform-admin access; this only hides the UI. */
export function OpsShell({ children }: { children: ReactNode }) {
  const query = useSessionQuery();
  const router = useRouter();
  const pathname = usePathname();
  const session = query.data;
  useEffect(() => {
    if (!session) return;
    if (!session.authenticated || session.state === "pending_mfa") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (session.state === "pending_enrollment") router.replace(`/mfa/setup?next=${encodeURIComponent(pathname)}`);
  }, [session, router, pathname]);
  if (query.isPending || !session || !session.authenticated || session.state !== "active") {
    return <div className="p-8" aria-busy="true"><TableSkeleton label="Loading" /></div>;
  }
  if (!session.is_platform_admin) {
    return (
      <main id="main" className="mx-auto mt-24 max-w-md p-8 text-center">
        <h1 className="text-xl font-semibold">Page not found</h1>
        <Link href="/app" className="mt-4 inline-block text-brand underline">Go to your dashboard</Link>
      </main>
    );
  }
  return (
    <SessionProvider value={session}>
      <a href="#main" className="sr-only-focusable fixed top-2 left-2 z-50 rounded bg-brand px-3 py-2 text-on-brand">Skip to content</a>
      <div className="flex min-h-screen flex-col">
        <header className="flex items-center justify-between border-b border-rule bg-surface px-4 py-2">
          <div className="flex items-center gap-3">
            <span className="font-semibold">{PRODUCT_NAME}</span>
            <span className="rounded bg-warning-soft px-2 py-0.5 text-xs font-medium text-warning">Operations console</span>
          </div>
          <UserMenu session={session} onHelp={() => undefined} />
        </header>
        <div className="flex flex-1 flex-col md:flex-row">
          <nav aria-label="Operations" className="border-b border-rule bg-surface p-3 md:w-56 md:border-r md:border-b-0">
            <ul className="flex flex-wrap gap-1 md:flex-col">
              {NAV.map(([href, label]) => {
                const active = href === "/ops" ? pathname === "/ops" || pathname.startsWith("/ops/tenants") : pathname.startsWith(href);
                return (
                  <li key={href}>
                    <Link href={href} aria-current={active ? "page" : undefined} className={`block rounded-md px-3 py-1.5 text-sm ${active ? "bg-brand-soft font-medium text-brand" : "hover:bg-surface-2"}`}>{label}</Link>
                  </li>
                );
              })}
            </ul>
          </nav>
          <main id="main" className="min-w-0 flex-1 p-4 md:p-8">{children}</main>
        </div>
      </div>
    </SessionProvider>
  );
}
