"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, errorMessage, unwrap } from "@/lib/api";
import type { ExportRecord } from "@/lib/types";

const TERMINAL = new Set(["succeeded", "failed", "expired"]);

/** Ask the API for a short-lived signed link, then let the browser download it. */
export async function downloadExport(id: string): Promise<void> {
  const link = unwrap(await api.POST("/api/v1/exports/{export_id}/link", { params: { path: { export_id: id } } }));
  const a = document.createElement("a");
  a.href = link.url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function waitFor(id: string): Promise<ExportRecord> {
  for (let i = 0; i < 600; i++) {
    const e = unwrap(await api.GET("/api/v1/exports/{export_id}", { params: { path: { export_id: id } } }));
    if (TERMINAL.has(e.status)) return e;
    await new Promise((r) => setTimeout(r, i < 10 ? 500 : 1500));
  }
  throw new Error("The export is taking longer than usual. It will appear under Recent exports when ready.");
}

/** Start an export (202), wait for the worker, then download. Returns whether it is busy. */
export function useExporter() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  async function run(label: string, start: () => Promise<ExportRecord>) {
    setBusy(label);
    try {
      const queued = await start();
      void qc.invalidateQueries({ queryKey: ["exports"] });
      const done = await waitFor(queued.id);
      void qc.invalidateQueries({ queryKey: ["exports"] });
      if (done.status !== "succeeded") {
        toast.error(done.error || "The export could not be created.");
        return;
      }
      await downloadExport(done.id);
      toast.success(`${done.filename} downloaded`);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }
  return { busy, run };
}
