import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_TERMS, TermsEditor } from "./terms-editor";
import type { Terms } from "@/lib/types";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return { ...real, api: { ...real.api, POST: post } };
});

function Harness({ onTerms }: { onTerms: (t: Terms) => void }) {
  const [terms, setTerms] = useState<Terms>(DEFAULT_TERMS);
  return <TermsEditor value={terms} onChange={(t) => { setTerms(t); onTerms(t); }} />;
}

function renderEditor(response: object, onTerms = vi.fn()) {
  post.mockResolvedValue({ data: response, response: new Response(null, { status: 200 }) });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><Harness onTerms={onTerms} /></QueryClientProvider>);
}

beforeEach(() => post.mockReset());

describe("TermsEditor", () => {
  it("shows the server-generated summary and sends rates as decimal strings", async () => {
    renderEditor({ valid: true, summary: "Pays 2.00% on eligible net spend.", warnings: ["Open-ended agreement."], error: null });
    expect(await screen.findByText("Pays 2.00% on eligible net spend.", undefined, { timeout: 3000 })).toBeTruthy();
    expect(screen.getByText("Open-ended agreement.")).toBeTruthy();
    const [path, init] = post.mock.calls[0] as [string, { body: Terms }];
    expect(path).toBe("/api/v1/agreement-terms/check");
    expect(init.body.components[0]?.rate).toBe("0.02"); // never a JS number
  });

  it("reveals tier rows when a tiered component is chosen", async () => {
    const onTerms = vi.fn();
    renderEditor({ valid: true, summary: "ok", warnings: [], error: null }, onTerms);
    const type = screen.getAllByLabelText("Type")[0] as HTMLSelectElement;
    await userEvent.selectOptions(type, "tiered_all_units");
    await waitFor(() => expect(onTerms).toHaveBeenCalled());
    const last = onTerms.mock.calls.at(-1)?.[0] as Terms;
    expect(last.components[0]?.type).toBe("tiered_all_units");
  });

  it("explains invalid terms with the server's message", async () => {
    renderEditor({ valid: false, summary: "", warnings: [], error: "Tier thresholds must increase." });
    expect(await screen.findByText("Tier thresholds must increase.", undefined, { timeout: 3000 })).toBeTruthy();
  });
});
