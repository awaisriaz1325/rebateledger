"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { can, useSession } from "@/lib/session";

const ITEMS: { href: string; label: string; permission?: string }[] = [
  { href: "/app/settings/profile", label: "Profile & sign-in" },
  { href: "/app/settings/notifications", label: "Notifications" },
  { href: "/app/settings/organization", label: "Organization", permission: "manage_settings" },
  { href: "/app/settings/security", label: "Security", permission: "manage_settings" },
  { href: "/app/settings/reconciliation", label: "Reconciliation", permission: "manage_settings" },
  { href: "/app/settings/approvals", label: "Approvals", permission: "manage_settings" },
  { href: "/app/settings/accounting", label: "Accounting", permission: "manage_settings" },
  { href: "/app/settings/members", label: "Members", permission: "manage_users" },
  { href: "/app/settings/templates", label: "Import templates", permission: "manage_imports" },
  { href: "/app/settings/plan", label: "Plan & usage", permission: "view_billing" },
  { href: "/app/settings/audit", label: "Audit log", permission: "view_audit" },
];

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const session = useSession();
  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <nav aria-label="Settings" className="shrink-0 lg:w-56">
        <h1 className="mb-3 text-2xl font-semibold tracking-tight">Settings</h1>
        <ul className="flex flex-wrap gap-1 lg:flex-col">
          {ITEMS.filter((i) => !i.permission || can(session, i.permission)).map((i) => (
            <li key={i.href}>
              <Link
                href={i.href}
                aria-current={pathname === i.href ? "page" : undefined}
                className={cn("block rounded-md px-3 py-1.5 text-sm", pathname === i.href ? "bg-brand-soft font-medium text-brand" : "hover:bg-surface-2")}
              >
                {i.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
