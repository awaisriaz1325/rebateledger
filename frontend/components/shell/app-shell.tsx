"use client";

import {
  BookOpenCheck,
  Calculator,
  Building2,
  ChartColumn,
  FileSpreadsheet,
  FileText,
  Gauge,
  HandCoins,
  LayoutDashboard,
  ListChecks,
  Menu as MenuIcon,
  PlayCircle,
  Receipt,
  Search,
  Settings,
  Target,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { CommandPalette } from "@/components/shell/command-palette";
import { NotificationBell } from "@/components/shell/notification-bell";
import { StepUpProvider } from "@/components/step-up";
import { UserMenu } from "@/components/shell/user-menu";
import { Button, Kbd } from "@/components/ui/core";
import { Dialog } from "@/components/ui/overlay";
import { TableSkeleton } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { PRODUCT_NAME } from "@/lib/site";
import { SessionProvider, can, useRefreshSession, useSessionQuery, type SessionInfo } from "@/lib/session";

interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
  permission?: string;
}

const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: "Overview",
    items: [
      { href: "/app", label: "Dashboard", icon: <LayoutDashboard size={16} /> },
      { href: "/app/tiers", label: "Tier tracker", icon: <Target size={16} /> },
    ],
  },
  {
    section: "Data",
    items: [
      { href: "/app/suppliers", label: "Suppliers", icon: <Building2 size={16} /> },
      { href: "/app/agreements", label: "Agreements", icon: <FileText size={16} /> },
      { href: "/app/agreements/model", label: "Deal modelling", icon: <Calculator size={16} />, permission: "edit_agreements" },
      { href: "/app/imports", label: "Imports", icon: <FileSpreadsheet size={16} /> },
    ],
  },
  {
    section: "Reconcile",
    items: [
      { href: "/app/runs", label: "Runs", icon: <PlayCircle size={16} /> },
      { href: "/app/results", label: "Results", icon: <Gauge size={16} /> },
      { href: "/app/discrepancies", label: "Discrepancies", icon: <ListChecks size={16} /> },
      { href: "/app/credits", label: "Credits", icon: <Receipt size={16} /> },
      { href: "/app/claims", label: "Claims", icon: <HandCoins size={16} /> },
      { href: "/app/approvals", label: "Approvals", icon: <BookOpenCheck size={16} /> },
    ],
  },
  {
    section: "Analyse",
    items: [{ href: "/app/reports", label: "Reports", icon: <ChartColumn size={16} /> }],
  },
];

export function AppShell({ children }: { children: ReactNode }) {
  const query = useSessionQuery();
  const router = useRouter();
  const pathname = usePathname();
  const session = query.data;

  useEffect(() => {
    if (!session) return;
    if (!session.authenticated) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (session.state === "pending_enrollment") router.replace(`/mfa/setup?next=${encodeURIComponent(pathname)}`);
    else if (session.state === "pending_mfa") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [session, router, pathname]);

  if (query.isPending || !session || !session.authenticated || session.state !== "active") {
    return (
      <div className="p-8" aria-busy="true">
        <TableSkeleton label="Loading your workspace" />
      </div>
    );
  }
  if (!session.organization) return <ChooseOrganization session={session} />;
  return (
    <SessionProvider value={session}>
      <StepUpProvider>
        <Shell session={session}>{children}</Shell>
      </StepUpProvider>
    </SessionProvider>
  );
}

function ChooseOrganization({ session }: { session: SessionInfo }) {
  const refresh = useRefreshSession();
  return (
    <main id="main" className="mx-auto mt-24 max-w-md rounded-lg border border-rule bg-surface p-8">
      <h1 className="text-xl font-semibold">Choose an organization</h1>
      {(session.organizations ?? []).length === 0 ? (
        <p className="mt-2 text-sm text-muted">You are not a member of any organization yet. Ask an administrator to invite you.</p>
      ) : (
        <ul className="mt-4 flex flex-col gap-2">
          {(session.organizations ?? []).map((o) => (
            <li key={o.id}>
              <Button
                variant="secondary"
                className="w-full justify-between"
                onClick={async () => refresh(unwrap(await api.POST("/api/v1/auth/switch-organization", { body: { organization_id: o.id } })))}
              >
                {o.name} <span className="text-xs text-muted capitalize">{o.role}</span>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function Shell({ session, children }: { session: SessionInfo; children: ReactNode }) {
  const pathname = usePathname();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      } else if (e.key === "?" && !typing) {
        setHelpOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Highlight only the most specific matching item (e.g. Deal modelling, not also Agreements).
  const activeHref = NAV.flatMap((g) => g.items)
    .map((i) => i.href)
    .filter((h) => (h === "/app" ? pathname === "/app" : pathname === h || pathname.startsWith(`${h}/`)))
    .sort((a, b) => b.length - a.length)[0];
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only-focusable fixed top-2 left-2 z-50 rounded bg-brand px-3 py-2 text-on-brand">
        Skip to content
      </a>
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 w-60 shrink-0 flex-col border-r border-rule bg-surface lg:static lg:flex",
          navOpen ? "flex" : "hidden",
        )}
        aria-label="Main navigation"
      >
        <div className="flex h-14 items-center gap-2 border-b border-rule px-4 font-semibold">
          <span aria-hidden="true" className="inline-block h-5 w-5 rounded-sm bg-brand" />
          {PRODUCT_NAME}
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {NAV.map((group) => (
            <div key={group.section} className="mb-4">
              <p className="px-2 pb-1 text-[11px] font-semibold tracking-wide text-muted uppercase">{group.section}</p>
              <ul>
                {group.items.filter((i) => !i.permission || can(session, i.permission)).map((item) => {
                  const active = item.href === activeHref;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        onClick={() => setNavOpen(false)}
                        className={cn(
                          "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm",
                          active ? "bg-brand-soft font-medium text-brand" : "text-ink hover:bg-surface-2",
                        )}
                      >
                        <span aria-hidden="true">{item.icon}</span>
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
        <div className="border-t border-rule p-2">
            <Link
              href="/app/settings"
              aria-current={pathname.startsWith("/app/settings") ? "page" : undefined}
              className={cn("flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm", pathname.startsWith("/app/settings") ? "bg-brand-soft font-medium text-brand" : "hover:bg-surface-2")}
            >
              <Settings size={16} aria-hidden="true" /> Settings
            </Link>
          </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-rule bg-surface/95 px-4 backdrop-blur">
          <button type="button" className="rounded p-1.5 hover:bg-surface-2 lg:hidden" aria-label="Open navigation" aria-expanded={navOpen} onClick={() => setNavOpen((o) => !o)}>
            <MenuIcon size={18} aria-hidden="true" />
          </button>
          <OrgSwitcher session={session} />
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="ml-2 hidden h-8 min-w-64 items-center gap-2 rounded-md border border-border-strong bg-surface px-3 text-sm text-muted hover:bg-surface-2 md:inline-flex"
          >
            <Search size={14} aria-hidden="true" /> Search or jump to…
            <span className="ml-auto"><Kbd>Ctrl K</Kbd></span>
          </button>
          <div className="ml-auto flex items-center gap-1">
            <NotificationBell />
            <UserMenu session={session} onHelp={() => setHelpOpen(true)} />
          </div>
        </header>
        <Banners session={session} />
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 lg:px-8">
          <Breadcrumbs />
          {children}
        </main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <Dialog open={helpOpen} onOpenChange={setHelpOpen} title="Keyboard shortcuts">
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt><Kbd>Ctrl/⌘ K</Kbd></dt><dd>Search and jump to any page</dd>
          <dt><Kbd>?</Kbd></dt><dd>Show this help</dd>
          <dt><Kbd>↑</Kbd> <Kbd>↓</Kbd></dt><dd>Move between table rows</dd>
          <dt><Kbd>Enter</Kbd></dt><dd>Open the focused row</dd>
          <dt><Kbd>Esc</Kbd></dt><dd>Close dialogs and drawers</dd>
        </dl>
      </Dialog>
    </div>
  );
}

function OrgSwitcher({ session }: { session: SessionInfo }) {
  const refresh = useRefreshSession();
  const router = useRouter();
  const org = session.organization;
  if (!org) return null;
  if ((session.organizations ?? []).length <= 1 || session.support_access) {
    return (
      <span className="truncate text-sm font-medium" title={org.name}>
        {org.name}
        {session.support_access ? <span className="ml-2 text-xs text-warning">(support access)</span> : null}
      </span>
    );
  }
  return (
    <>
      <label htmlFor="org-switcher" className="sr-only">Organization</label>
      <select
        id="org-switcher"
        value={org.id}
        onChange={async (e) => {
          await refresh(unwrap(await api.POST("/api/v1/auth/switch-organization", { body: { organization_id: e.target.value } })));
          router.push("/app");
        }}
        className="h-8 max-w-64 rounded-md border border-border-strong bg-surface px-2 text-sm font-medium"
      >
        {(session.organizations ?? []).map((o) => (
          <option key={o.id} value={o.id}>{o.name}</option>
        ))}
      </select>
    </>
  );
}

function Banners({ session }: { session: SessionInfo }) {
  const status = session.organization?.billing_status;
  return (
    <div className="flex flex-col">
      {session.support_access ? <SupportSessionBanner session={session} /> : null}
      <SupportGrantBanner session={session} />
      {status === "suspended" ? (
        <div role="status" className="border-b border-negative/30 bg-negative-soft px-4 py-2 text-sm">
          <strong>This organization is read-only.</strong> You can view and export everything; imports, runs and edits are paused. {can(session, "view_billing") ? <Link href="/app/settings/plan#invoices" className="font-medium underline">See invoices</Link> : "Contact your account owner."}
        </div>
      ) : status === "past_due" ? (
        <div role="status" className="border-b border-warning/30 bg-warning-soft px-4 py-2 text-sm">
          A {PRODUCT_NAME} invoice is overdue. {can(session, "view_billing") ? <Link href="/app/settings/plan#invoices" className="font-medium underline">See invoices</Link> : "Your account owner has the details."}
        </div>
      ) : null}
      <AnnouncementBanner />
    </div>
  );
}

function SupportSessionBanner({ session }: { session: SessionInfo }) {
  const router = useRouter();
  const qc = useQueryClient();
  const access = session.support_access;
  if (!access) return null;
  return (
    <div role="status" className="flex flex-wrap items-center gap-3 border-b border-warning/30 bg-warning-soft px-4 py-2 text-sm">
      Support access is active ({access.scope.replace("_", "-")}) until {formatDateTime(access.expires_at)}. Every action is recorded in the organization&rsquo;s audit log.
      <Button size="sm" variant="secondary" onClick={async () => { unwrap(await api.POST("/api/v1/ops/support/exit")); await qc.invalidateQueries(); router.push("/ops"); }}>Exit support access</Button>
    </div>
  );
}

function AnnouncementBanner() {
  const query = useQuery({ queryKey: ["announcements"], queryFn: async () => unwrap(await api.GET("/api/v1/announcements")), staleTime: 300_000 });
  const [dismissed, setDismissed] = useState<string[]>([]);
  const items = (query.data ?? []).filter((a) => !dismissed.includes(a.id));
  if (!items.length) return null;
  return (
    <>
      {items.map((a) => (
        <div key={a.id} role="status" className={`flex items-center justify-between gap-3 border-b px-4 py-2 text-sm ${a.level === "warning" ? "border-warning/30 bg-warning-soft" : "border-info/30 bg-info-soft"}`}>
          <span>{a.message}</span>
          <button type="button" className="text-xs underline" onClick={() => setDismissed([...dismissed, a.id])}>Dismiss</button>
        </div>
      ))}
    </>
  );
}

/** Tenant members see an active support-access grant and can revoke it (SPEC §4.15). */
function SupportGrantBanner({ session }: { session: SessionInfo }) {
  // Same query key as the security settings page, so granting or revoking updates this banner at once.
  const query = useQuery({
    queryKey: ["support-access"],
    enabled: !session.support_access,
    queryFn: async () => unwrap(await api.GET("/api/v1/org/support-access")),
  });
  const grants = query.data ?? [];
  if (!grants.length) return null;
  const g = grants[0];
  return (
    <div role="status" className="flex flex-wrap items-center gap-3 border-b border-warning/30 bg-warning-soft px-4 py-2 text-sm">
      The {PRODUCT_NAME} support team has {g.scope.replace("_", "-")} access to this organization until {formatDateTime(g.expires_at)}.
      {can(session, "manage_support_access") ? (
        <Link href="/app/settings/security" className="font-medium text-brand underline">Manage or revoke</Link>
      ) : null}
    </div>
  );
}

const LABELS: Record<string, string> = {
  app: "Dashboard", suppliers: "Suppliers", agreements: "Agreements", imports: "Imports", runs: "Runs", results: "Results",
  discrepancies: "Discrepancies", credits: "Credits", claims: "Claims", tiers: "Tier tracker", settings: "Settings", reports: "Reports",
  approvals: "Approvals", new: "New", model: "Deal modelling", profile: "Profile", security: "Security", organization: "Organization", members: "Members",
  reconciliation: "Reconciliation", notifications: "Notifications", templates: "Import templates", plan: "Plan & usage", audit: "Audit log", data: "Data",
};

function Breadcrumbs() {
  const pathname = usePathname();
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length <= 1) return null;
  const crumbs = parts.map((p, i) => ({ href: "/" + parts.slice(0, i + 1).join("/"), label: LABELS[p] ?? (p.length > 20 ? "Details" : p) }));
  return (
    <nav aria-label="Breadcrumb" className="mb-3 text-xs text-muted">
      <ol className="flex flex-wrap items-center gap-1">
        {crumbs.map((c, i) => (
          <li key={c.href} className="flex items-center gap-1">
            {i > 0 ? <span aria-hidden="true">/</span> : null}
            {i === crumbs.length - 1 ? <span aria-current="page">{c.label}</span> : <Link href={c.href} className="hover:underline">{c.label}</Link>}
          </li>
        ))}
      </ol>
    </nav>
  );
}
