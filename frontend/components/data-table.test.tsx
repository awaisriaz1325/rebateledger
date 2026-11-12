import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DataTable, compareDecimal } from "./data-table";

describe("compareDecimal (exact, no float conversion)", () => {
  it("orders signs, integer lengths and fractions correctly", () => {
    const values = ["10.5", "-2", "9.99", "100", "-10.01", "0.001", "", "9.990000000000000001"];
    expect([...values].sort(compareDecimal)).toEqual(["", "-10.01", "-2", "0.001", "9.99", "9.990000000000000001", "10.5", "100"]);
    expect(compareDecimal("1.10", "1.1")).toBe(0);
    expect(compareDecimal("007", "7")).toBe(0);
  });
});

type Row = { id: string; name: string; amount: string };
const rows: Row[] = [
  { id: "a", name: "Acme", amount: "100.00" },
  { id: "b", name: "Bolt", amount: "-5.25" },
  { id: "c", name: "Core", amount: "20.10" },
];

describe("DataTable", () => {
  const columns = [
    { id: "name", header: "Supplier", value: (r: Row) => r.name },
    { id: "amount", header: "Amount", value: (r: Row) => r.amount, numeric: true, align: "right" as const },
    { id: "act", header: "", value: () => "", cell: () => <button type="button">Explain</button> },
  ];

  it("sorts money numerically and names action columns for screen readers", async () => {
    render(<DataTable label="Test" rows={rows} rowKey={(r) => r.id} columns={columns} />);
    const table = screen.getByRole("table", { name: "Test" });
    expect(within(table).getByText("Actions").className).toContain("sr-only");
    await userEvent.click(within(table).getByRole("button", { name: /Amount/ }));
    const names = within(table).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0]?.textContent);
    expect(names).toEqual(["Bolt", "Core", "Acme"]);
  });

  it("filters across columns", async () => {
    render(<DataTable label="Test" rows={rows} rowKey={(r) => r.id} columns={columns} />);
    await userEvent.type(screen.getByRole("searchbox", { name: /filter/i }), "cor");
    const table = screen.getByRole("table", { name: "Test" });
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(within(table).getByText("Core")).toBeTruthy();
  });
});
