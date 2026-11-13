"use client";

import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { Dialog as D } from "radix-ui";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useReturnFocus } from "@/components/ui/overlay";
import { api } from "@/lib/api";

const PAGES = [
  ["Dashboard", "/app"], ["Suppliers", "/app/suppliers"], ["New supplier", "/app/suppliers/new"], ["Agreements", "/app/agreements"],
  ["New agreement", "/app/agreements/new"], ["Deal modelling", "/app/agreements/model"], ["Imports", "/app/imports"], ["New import", "/app/imports/new"], ["Runs", "/app/runs"],
  ["Results", "/app/results"], ["Discrepancies", "/app/discrepancies"], ["Credits", "/app/credits"], ["Claims", "/app/claims"],
  ["Approvals", "/app/approvals"], ["Tier tracker", "/app/tiers"], ["Reports", "/app/reports"], ["Settings", "/app/settings"],
  ["Members", "/app/settings/members"], ["Audit log", "/app/settings/audit"],
] as const;

function useDebounced(value: string, ms = 200): string {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Ctrl/⌘-K: jump to pages and search suppliers, agreements, claims and imports (SPEC §10). */
export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const enabled = open && q.length >= 2;
  const suppliers = useQuery({ queryKey: ["palette", "suppliers", q], enabled, queryFn: async () => (await api.GET("/api/v1/suppliers", { params: { query: { q, limit: 5 } } })).data?.items ?? [] });
  const agreements = useQuery({ queryKey: ["palette", "agreements", q], enabled, queryFn: async () => (await api.GET("/api/v1/agreements", { params: { query: { q, limit: 5 } } })).data?.items ?? [] });
  const claims = useQuery({
    queryKey: ["palette", "claims", q], enabled,
    queryFn: async () => ((await api.GET("/api/v1/claims", { params: { query: { limit: 50 } } })).data?.items ?? []).filter((c) => `CL-${String(c.number).padStart(4, "0")} ${c.title}`.toLowerCase().includes(q.toLowerCase())).slice(0, 5),
  });
  const imports = useQuery({
    queryKey: ["palette", "imports", q], enabled,
    queryFn: async () => ((await api.GET("/api/v1/imports", { params: { query: { limit: 50 } } })).data?.items ?? []).filter((b) => b.filename.toLowerCase().includes(q.toLowerCase())).slice(0, 5),
  });
  function go(href: string) {
    onOpenChange(false);
    setSearch("");
    router.push(href);
  }
  const item = "flex cursor-pointer items-center justify-between rounded px-3 py-2 text-sm aria-selected:bg-brand-soft aria-selected:text-brand";
  const focus = useReturnFocus();
  const group = "px-1 py-1 text-xs text-muted [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:font-semibold";
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <D.Content {...focus} className="fixed top-24 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-lg border border-rule bg-surface shadow-card">
          <D.Title className="sr-only">Search and jump to</D.Title>
          <D.Description className="sr-only">Type to search pages, suppliers, agreements, claims and imports.</D.Description>
          <Command label="Command palette" shouldFilter={false}>
            <Command.Input value={search} onValueChange={setSearch} placeholder="Search suppliers, agreements, claims, imports…" className="h-12 w-full border-b border-rule bg-transparent px-4 text-sm outline-none" />
            <Command.List className="max-h-96 overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-sm text-muted">No matches.</Command.Empty>
              <Command.Group heading="Pages" className={group}>
                {PAGES.filter(([label]) => label.toLowerCase().includes(search.toLowerCase())).map(([label, href]) => (
                  <Command.Item key={href} value={`page-${href}`} onSelect={() => go(href)} className={item}>{label}</Command.Item>
                ))}
              </Command.Group>
              {(suppliers.data ?? []).length ? (
                <Command.Group heading="Suppliers" className={group}>
                  {suppliers.data!.map((s) => <Command.Item key={s.id} value={`s-${s.id}`} onSelect={() => go(`/app/suppliers/${s.id}`)} className={item}>{s.name}<span className="font-mono text-xs text-muted">{s.codes.join(", ")}</span></Command.Item>)}
                </Command.Group>
              ) : null}
              {(agreements.data ?? []).length ? (
                <Command.Group heading="Agreements" className={group}>
                  {agreements.data!.map((a) => <Command.Item key={a.id} value={`a-${a.id}`} onSelect={() => go(`/app/agreements/${a.id}`)} className={item}>{a.name}<span className="text-xs text-muted">{a.external_reference}</span></Command.Item>)}
                </Command.Group>
              ) : null}
              {(claims.data ?? []).length ? (
                <Command.Group heading="Claims" className={group}>
                  {claims.data!.map((c) => <Command.Item key={c.id} value={`c-${c.id}`} onSelect={() => go(`/app/claims/${c.id}`)} className={item}>CL-{String(c.number).padStart(4, "0")} · {c.title}</Command.Item>)}
                </Command.Group>
              ) : null}
              {(imports.data ?? []).length ? (
                <Command.Group heading="Imports" className={group}>
                  {imports.data!.map((b) => <Command.Item key={b.id} value={`i-${b.id}`} onSelect={() => go(`/app/imports/${b.id}`)} className={item}>{b.filename}<span className="text-xs text-muted">{b.import_type}</span></Command.Item>)}
                </Command.Group>
              ) : null}
            </Command.List>
          </Command>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
