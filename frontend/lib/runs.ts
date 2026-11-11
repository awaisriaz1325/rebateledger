/** Run display helpers. */
export function scopeText(scope: Record<string, unknown>, names?: { supplier: Map<string, string> }): string {
  if (scope.type === "supplier") return `Supplier: ${names?.supplier.get(String(scope.supplier_id)) ?? "one supplier"}`;
  if (scope.type === "agreements") return `${(scope.agreement_ids as string[] | undefined)?.length ?? 0} agreement(s)`;
  return "All agreements";
}
