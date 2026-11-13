import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ImportMapping } from "./import-mapping";
import type { Batch, ImportPreview } from "@/lib/types";

const batch: Batch = {
  id: "b1", import_type: "purchases", status: "uploaded", filename: "p.csv", file_format: "csv", size_bytes: 10,
  config: { header_row: 1, columns: {}, flags: {}, confirmed: false }, stats: {}, commit_mode: null, duplicate_of_batch_id: null,
  created_at: "2026-11-12T00:00:00Z", validated_at: null, committed_at: null, voided_at: null, void_reason: "", job_id: null,
};

const preview: ImportPreview = {
  header: ["Vendor Code", "Invoice No", "SKU", "Qty", "Amount", "Invoice Date"],
  sample_rows: [["ACME", "I1", "A", "1", "10.00", "03/04/2025"]],
  suggested_columns: { supplier_code: "Vendor Code", invoice_number: "Invoice No", sku: "SKU", quantity: "Qty", amount: "Amount", invoice_date: "Invoice Date" },
  date_format_candidates: { "Invoice Date": ["MM/DD/YYYY", "DD/MM/YYYY"] },
  fields: [
    { name: "supplier_code", label: "Supplier code", required: true, kind: "code" },
    { name: "invoice_number", label: "Invoice number", required: true, kind: "text" },
    { name: "sku", label: "SKU", required: true, kind: "text" },
    { name: "quantity", label: "Quantity", required: true, kind: "decimal" },
    { name: "amount", label: "Extended amount", required: true, kind: "decimal" },
    { name: "invoice_date", label: "Invoice date", required: false, kind: "date" },
  ],
  supports_flags: true,
  preset_suggestion: null,
  applied_preset_id: null,
};

describe("ImportMapping", () => {
  it("never guesses an ambiguous date: saving waits for an explicit choice", async () => {
    const onSave = vi.fn();
    render(<ImportMapping batch={batch} preview={preview} saving={false} onSave={onSave} />);
    expect(screen.getByText("Dates are ambiguous")).toBeTruthy();
    const save = screen.getByRole("button", { name: "Save mapping and preview" });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    // Both fitting formats are marked as matching the sample.
    expect(screen.getByRole("option", { name: "MM/DD/YYYY (matches sample)" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "DD/MM/YYYY (matches sample)" })).toBeTruthy();

    await userEvent.selectOptions(screen.getByLabelText(/Date format/), "DD/MM/YYYY");
    expect((save as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(save);
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ date_format: "DD/MM/YYYY", columns: preview.suggested_columns, decimal_separator: ".", negative_style: "minus" }),
    );
  });

  it("blocks saving while a required field is unmapped", async () => {
    render(<ImportMapping batch={batch} preview={{ ...preview, suggested_columns: { supplier_code: "Vendor Code" } }} saving={false} onSave={vi.fn()} />);
    expect(screen.getByText(/Map the required fields: Invoice number, SKU, Quantity, Extended amount/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Save mapping and preview" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("switching to comma decimals also switches the thousands separator", async () => {
    const onSave = vi.fn();
    render(<ImportMapping batch={batch} preview={{ ...preview, date_format_candidates: {}, suggested_columns: { ...preview.suggested_columns, invoice_date: "" } }} saving={false} onSave={onSave} />);
    await userEvent.selectOptions(screen.getByLabelText("Decimal separator"), ",");
    await userEvent.click(screen.getByRole("button", { name: "Save mapping and preview" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ decimal_separator: ",", thousands_separator: "." }));
  });
});
