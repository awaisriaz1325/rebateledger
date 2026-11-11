/** Client-side CSV of the current table view, with the same formula-injection rule as the backend. */
const DANGEROUS = ["=", "+", "-", "@", "\t", "\r"];

export function neutralize(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return DANGEROUS.some((p) => text.startsWith(p)) ? `'${text}` : text;
}

function quote(text: string): string {
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function toCsv(header: string[], rows: unknown[][]): string {
  return [header, ...rows].map((r) => r.map((c) => quote(neutralize(c))).join(",")).join("\r\n") + "\r\n";
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
