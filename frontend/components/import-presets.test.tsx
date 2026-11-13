import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ImportPresets } from "./import-presets";
import type { Batch, ImportPreview } from "@/lib/types";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return { ...real, api: { ...real.api, GET: get, POST: post } };
});

const batch: Batch = {
  id: "b1", import_type: "purchases", status: "uploaded", filename: "p.csv", file_format: "csv", size_bytes: 10,
  config: { header_row: 1, columns: {}, flags: {}, confirmed: false }, stats: {}, commit_mode: null, duplicate_of_batch_id: null,
  created_at: "2026-11-13T00:00:00Z", validated_at: null, committed_at: null, voided_at: null, void_reason: "", job_id: null,
};

const preview: ImportPreview = {
  header: ["Supplier ID", "Item ID"], sample_rows: [], suggested_columns: {}, date_format_candidates: {}, fields: [], supports_flags: true,
  preset_suggestion: { id: "p21-purchases", erp: "Epicor Prophet 21", report: "PO receipt / purchase history export", verified: false },
  applied_preset_id: null,
};

const PRESETS = [
  { id: "p21-purchases", erp: "Epicor Prophet 21", report: "PO receipt / purchase history export", import_type: "purchases", verified: false, notes: "", columns: {}, config: {} },
  { id: "qbo-purchases", erp: "QuickBooks Online", report: "Purchases by Product/Service Detail", import_type: "purchases", verified: false, notes: "", columns: {}, config: {} },
];

const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });

function renderPresets(p: ImportPreview = preview, onApplied = vi.fn()) {
  get.mockResolvedValue(ok(PRESETS));
  post.mockResolvedValue(ok({ ...batch }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ImportPresets batch={batch} preview={p} onApplied={onApplied} /></QueryClientProvider>);
  return onApplied;
}

beforeEach(() => { get.mockReset(); post.mockReset(); });

describe("ImportPresets", () => {
  it("offers the recognised ERP and applies it only when the user clicks", async () => {
    const onApplied = renderPresets();
    expect(screen.getByText("This looks like an export from Epicor Prophet 21")).toBeTruthy();
    expect(screen.getByText(/Unverified preset:/)).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Use Epicor Prophet 21 mapping" }));
    await waitFor(() => expect(onApplied).toHaveBeenCalled());
    const [path, init] = post.mock.calls[0] as [string, { body: { preset_id: string } }];
    expect(path).toBe("/api/v1/imports/{batch_id}/preset");
    expect(init.body.preset_id).toBe("p21-purchases");
  });

  it("lets the user pick any preset, marked unverified", async () => {
    renderPresets({ ...preview, preset_suggestion: null });
    const select = screen.getByLabelText("Fill the mapping from an ERP report");
    await screen.findByRole("option", { name: "QuickBooks Online — Purchases by Product/Service Detail (unverified)" });
    const apply = screen.getByRole("button", { name: "Apply preset" }) as HTMLButtonElement;
    expect(apply.disabled).toBe(true);
    await userEvent.selectOptions(select, "qbo-purchases");
    await userEvent.click(apply);
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect((post.mock.calls[0] as [string, { body: { preset_id: string } }])[1].body.preset_id).toBe("qbo-purchases");
  });

  it("after applying, reminds the user to check every column", async () => {
    renderPresets({ ...preview, applied_preset_id: "p21-purchases" });
    expect(await screen.findByText("Mapping from the Epicor Prophet 21 preset")).toBeTruthy();
    expect(screen.getByText(/not yet verified against a real export/)).toBeTruthy();
  });
});
