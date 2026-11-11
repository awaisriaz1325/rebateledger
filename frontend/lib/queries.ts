"use client";

/** Shared fetchers (cursor-paged lists loaded fully for client-side tables). */
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api";
import type { Agreement, Supplier } from "@/lib/types";

export async function fetchAllSuppliers(): Promise<Supplier[]> {
  const out: Supplier[] = [];
  let cursor: string | undefined;
  do {
    const page = unwrap(await api.GET("/api/v1/suppliers", { params: { query: { cursor, limit: 200 } } }));
    out.push(...page.items);
    cursor = page.next_cursor ?? undefined;
  } while (cursor);
  return out;
}

export async function fetchAllAgreements(): Promise<Agreement[]> {
  const out: Agreement[] = [];
  let cursor: string | undefined;
  do {
    const page = unwrap(await api.GET("/api/v1/agreements", { params: { query: { cursor, limit: 200 } } }));
    out.push(...page.items);
    cursor = page.next_cursor ?? undefined;
  } while (cursor);
  return out;
}

/** Supplier and agreement id → name maps, for tables whose rows carry only ids. */
export function useNames() {
  return useQuery({
    queryKey: ["names"],
    queryFn: async () => {
      const [suppliers, agreements] = await Promise.all([fetchAllSuppliers(), fetchAllAgreements()]);
      return {
        suppliers,
        agreements,
        supplier: new Map(suppliers.map((s) => [s.id, s.name])),
        agreement: new Map(agreements.map((a) => [a.id, a.name])),
      };
    },
    staleTime: 60_000,
  });
}
