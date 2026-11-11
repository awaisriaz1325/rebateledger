"use client";

/**
 * Data table (SPEC §10): sorting, filtering, column visibility, sticky header,
 * row virtualisation above 500 rows, CSV export of the current view, keyboard
 * row navigation. Built on TanStack Table v9 + TanStack Virtual.
 */
import {
  columnFilteringFeature,
  columnVisibilityFeature,
  createColumnHelper,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_includesString,
  globalFilteringFeature,
  rowSortingFeature,
  type RowData,
  sortFn_alphanumeric,
  sortFn_basic,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, ArrowUpDown, Download, Settings2 } from "lucide-react";
import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Button, Input } from "@/components/ui/core";
import { cn } from "@/lib/cn";
import { downloadCsv, toCsv } from "@/lib/csv";

export const VIRTUALIZE_ABOVE = 500;
const ROW_HEIGHT = 36;

const features = tableFeatures({
  rowSortingFeature,
  columnVisibilityFeature,
  columnFilteringFeature,
  globalFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric, basic: sortFn_basic },
  filterFns: { includesString: filterFn_includesString },
});

export interface Column<T extends RowData> {
  id: string;
  /** Empty string marks an unsortable action column (announced as "Actions"). */
  header: string;
  /** Plain value used for sorting, filtering and CSV export. Money stays a decimal string. */
  value: (row: T) => string | number | null | undefined;
  cell?: (row: T) => ReactNode;
  align?: "left" | "right";
  /** Sort decimal strings numerically without converting money to JS numbers for arithmetic. */
  numeric?: boolean;
  hidden?: boolean;
  width?: string;
}

/** Compare decimal strings exactly (no float conversion): sign, integer length, then lexicographic. */
export function compareDecimal(a: string | null | undefined, b: string | null | undefined): number {
  if (a == null || a === "") return b == null || b === "" ? 0 : -1;
  if (b == null || b === "") return 1;
  const na = a.startsWith("-"), nb = b.startsWith("-");
  if (na !== nb) return na ? -1 : 1;
  const sign = na ? -1 : 1;
  const [ai, af = ""] = a.replace("-", "").split(".");
  const [bi, bf = ""] = b.replace("-", "").split(".");
  const ia = ai.replace(/^0+(?=\d)/, ""), ib = bi.replace(/^0+(?=\d)/, "");
  if (ia.length !== ib.length) return sign * (ia.length - ib.length);
  if (ia !== ib) return sign * (ia < ib ? -1 : 1);
  const len = Math.max(af.length, bf.length);
  const fa = af.padEnd(len, "0"), fb = bf.padEnd(len, "0");
  return fa === fb ? 0 : sign * (fa < fb ? -1 : 1);
}

export function DataTable<T extends RowData>({
  rows,
  columns,
  label,
  rowKey,
  onRowClick,
  exportName,
  toolbar,
  height = 560,
  filterPlaceholder = "Filter rows",
}: {
  rows: T[];
  columns: Column<T>[];
  label: string;
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  exportName?: string;
  toolbar?: ReactNode;
  height?: number;
  filterPlaceholder?: string;
}) {
  const helper = useMemo(() => createColumnHelper<typeof features, T>(), []);
  const tableColumns = useMemo(
    () =>
      helper.columns(
        columns.map((c) =>
          helper.accessor((row: T) => c.value(row) ?? "", {
            id: c.id,
            header: c.header,
            sortFn: c.numeric
              ? (a, b, id) => compareDecimal(String(a.getValue(id) ?? ""), String(b.getValue(id) ?? ""))
              : "alphanumeric",
          }),
        ),
      ),
    [columns, helper],
  );
  const initialVisibility = useMemo(() => Object.fromEntries(columns.filter((c) => c.hidden).map((c) => [c.id, false])), [columns]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [showColumns, setShowColumns] = useState(false);
  const table = useTable({
    features,
    columns: tableColumns,
    data: rows,
    getRowId: (row: T) => rowKey(row),
    initialState: { columnVisibility: initialVisibility },
    state: { globalFilter },
    onGlobalFilterChange: (v) => setGlobalFilter(typeof v === "function" ? v(globalFilter) : v),
    globalFilterFn: "includesString",
  });
  const byId = useMemo(() => new Map(columns.map((c) => [c.id, c])), [columns]);
  const model = table.getRowModel().rows;
  const visible = table.getVisibleLeafColumns();
  const virtual = model.length > VIRTUALIZE_ABOVE;
  const scrollRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual's API is not memoisable; this component opts out of React Compiler optimisation.
  const virtualizer = useVirtualizer({
    count: model.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    enabled: virtual,
  });
  const items = virtual ? virtualizer.getVirtualItems() : model.map((_, index) => ({ index, start: index * ROW_HEIGHT, key: index }));
  const padTop = virtual && items.length ? items[0].start : 0;
  const padBottom = virtual && items.length ? virtualizer.getTotalSize() - items[items.length - 1].start - ROW_HEIGHT : 0;

  function exportCsv() {
    const header = visible.map((c) => byId.get(c.id)?.header ?? c.id);
    const data = model.map((r) => visible.map((c) => byId.get(c.id)?.value(r.original) ?? ""));
    downloadCsv(`${exportName ?? "export"}.csv`, toCsv(header, data));
  }

  function onKey(e: KeyboardEvent<HTMLTableRowElement>, index: number, row: T) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = index + (e.key === "ArrowDown" ? 1 : -1);
      if (next < 0 || next >= model.length) return;
      if (virtual) virtualizer.scrollToIndex(next);
      requestAnimationFrame(() => scrollRef.current?.querySelector<HTMLElement>(`[data-row-index="${next}"]`)?.focus());
    } else if (e.key === "Enter" && onRowClick) {
      onRowClick(row);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={`${label}-filter`} className="sr-only">
          {filterPlaceholder}
        </label>
        <Input
          id={`${label}-filter`}
          type="search"
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
          placeholder={filterPlaceholder}
          className="max-w-xs"
        />
        <span className="text-xs text-muted" aria-live="polite">
          {model.length.toLocaleString("en-US")} of {rows.length.toLocaleString("en-US")} rows
        </span>
        <div className="ml-auto flex flex-wrap gap-2">
          {toolbar}
          <div className="relative">
            <Button variant="secondary" size="sm" aria-expanded={showColumns} onClick={() => setShowColumns((s) => !s)}>
              <Settings2 size={14} aria-hidden="true" /> Columns
            </Button>
            {showColumns ? (
              <fieldset className="absolute right-0 z-20 mt-1 w-56 rounded-md border border-rule bg-surface p-3 shadow-card">
                <legend className="sr-only">Visible columns</legend>
                {table.getAllLeafColumns().map((col) => (
                  <label key={col.id} className="flex items-center gap-2 py-1 text-sm">
                    <input type="checkbox" checked={col.getIsVisible()} onChange={col.getToggleVisibilityHandler()} />
                    {byId.get(col.id)?.header ?? col.id}
                  </label>
                ))}
              </fieldset>
            ) : null}
          </div>
          {exportName ? (
            <Button variant="secondary" size="sm" onClick={exportCsv}>
              <Download size={14} aria-hidden="true" /> CSV
            </Button>
          ) : null}
        </div>
      </div>
      <div ref={scrollRef} className="overflow-auto rounded-lg border border-rule bg-surface" style={{ maxHeight: height }}>
        <table className="w-full border-collapse text-sm" aria-label={label} aria-rowcount={model.length + 1}>
          <thead className="sticky top-0 z-10 bg-surface-2">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const col = byId.get(header.column.id);
                  const sorted = header.column.getIsSorted();
                  if (!col?.header) {
                    // Action column (e.g. "Explain"): nothing to sort by, but headers still need a name.
                    return (
                      <th key={header.id} scope="col" className="border-b border-rule px-3 py-2" style={col?.width ? { width: col.width } : undefined}>
                        <span className="sr-only">Actions</span>
                      </th>
                    );
                  }
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                      className={cn("border-b border-rule px-3 py-2 text-xs font-semibold text-muted uppercase", col?.align === "right" ? "text-right" : "text-left")}
                      style={col?.width ? { width: col.width } : undefined}
                    >
                      <button type="button" onClick={header.column.getToggleSortingHandler()} className={cn("inline-flex items-center gap-1 uppercase", col?.align === "right" && "flex-row-reverse")}>
                        {col?.header}
                        {sorted === "asc" ? <ArrowUp size={12} aria-hidden="true" /> : sorted === "desc" ? <ArrowDown size={12} aria-hidden="true" /> : <ArrowUpDown size={12} aria-hidden="true" className="opacity-40" />}
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {padTop > 0 ? <tr aria-hidden="true" style={{ height: padTop }} /> : null}
            {items.map((item) => {
              const row = model[item.index];
              return (
                <tr
                  key={row.id}
                  data-row-index={item.index}
                  aria-rowindex={item.index + 2}
                  tabIndex={0}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  onKeyDown={(e) => onKey(e, item.index, row.original)}
                  className={cn("border-b border-rule last:border-0 focus:bg-brand-soft", onRowClick && "cursor-pointer hover:bg-surface-2")}
                  style={{ height: ROW_HEIGHT }}
                >
                  {visible.map((c) => {
                    const col = byId.get(c.id);
                    return (
                      <td key={c.id} className={cn("px-3 py-1.5", col?.align === "right" && "num")}>
                        {col?.cell ? col.cell(row.original) : String(col?.value(row.original) ?? "")}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {padBottom > 0 ? <tr aria-hidden="true" style={{ height: padBottom }} /> : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
