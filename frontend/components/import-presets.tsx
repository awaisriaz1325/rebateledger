"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Field, Notice, Select } from "@/components/ui/core";
import { api, errorMessage, unwrap } from "@/lib/api";
import type { Batch, ImportPreview } from "@/lib/types";
import type { components } from "@/generated/api";

type ImportType = components["schemas"]["ImportType"];

/**
 * ERP presets on the mapping step (v1.1 Phase 12). A preset only fills the mapping; the
 * user still checks every column and saves. Presets are unverified best guesses (ADR 0017).
 */
export function ImportPresets({ batch, preview, onApplied }: { batch: Batch; preview: ImportPreview; onApplied: () => void }) {
  const presets = useQuery({
    queryKey: ["import-presets", batch.import_type],
    queryFn: async () => unwrap(await api.GET("/api/v1/import-presets", { params: { query: { import_type: batch.import_type as ImportType } } })),
  });
  const [choice, setChoice] = useState("");
  const apply = useMutation({
    mutationFn: async (preset_id: string) => unwrap(await api.POST("/api/v1/imports/{batch_id}/preset", { params: { path: { batch_id: batch.id } }, body: { preset_id } })),
    onSuccess: () => {
      toast.success("Preset applied. Check each column, then save the mapping.");
      onApplied();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const list = presets.data ?? [];
  if (presets.isSuccess && list.length === 0) return null;
  const suggestion = preview.preset_suggestion;
  const applied = preview.applied_preset_id ? list.find((p) => p.id === preview.applied_preset_id) : undefined;

  return (
    <div className="flex flex-col gap-3">
      {applied ? (
        <Notice tone="info" title={`Mapping from the ${applied.erp} preset`}>
          {applied.verified ? null : "This preset is not yet verified against a real export. "}Check every column below before you save.
        </Notice>
      ) : suggestion ? (
        <Notice
          tone="info"
          title={`This looks like an export from ${suggestion.erp}`}
          action={<Button size="sm" loading={apply.isPending} onClick={() => apply.mutate(suggestion.id)}>Use {suggestion.erp} mapping</Button>}
        >
          {suggestion.report}. {suggestion.verified ? "" : "Unverified preset: "}you will still check every column.
        </Notice>
      ) : null}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (choice) apply.mutate(choice);
        }}
      >
        <Field id="erp-preset" label="Fill the mapping from an ERP report" hint="Optional. Unverified presets are best guesses.">
          <Select id="erp-preset" value={choice} onChange={(e) => setChoice(e.target.value)} disabled={!presets.isSuccess}>
            <option value="">Choose an ERP report…</option>
            {list.map((p) => (
              <option key={p.id} value={p.id}>
                {p.erp} — {p.report}{p.verified ? "" : " (unverified)"}
              </option>
            ))}
          </Select>
        </Field>
        <Button type="submit" variant="secondary" disabled={!choice} loading={apply.isPending}>Apply preset</Button>
      </form>
    </div>
  );
}
