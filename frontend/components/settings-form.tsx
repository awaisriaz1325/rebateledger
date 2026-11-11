"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { useStepUp } from "@/components/step-up";
import { Button, Card, Checkbox, Field, Input, Notice, Select } from "@/components/ui/core";
import { QueryState } from "@/components/ui/states";
import { ApiError, api, errorMessage, unwrap } from "@/lib/api";
import { isConflict, useVersioned } from "@/lib/etag";
import type { components } from "@/generated/api";

export type Org = components["schemas"]["OrgOut"];
type Section = "profile" | "security" | "reconciliation" | "approvals";

export type FieldDef =
  | { name: keyof Org & string; label: string; kind: "text" | "decimal" | "integer"; hint?: string }
  | { name: keyof Org & string; label: string; kind: "bool"; hint?: string }
  | { name: keyof Org & string; label: string; kind: "select"; options: { value: string; label: string }[]; hint?: string }
  | { name: keyof Org & string; label: string; kind: "list"; hint?: string };

export const ORG_KEY = ["org"] as const;

export function useOrg() {
  return useVersioned<Org>(ORG_KEY, () => api.GET("/api/v1/org"));
}

const PATHS: Record<Section, "/api/v1/org/settings/profile" | "/api/v1/org/settings/security" | "/api/v1/org/settings/reconciliation" | "/api/v1/org/settings/approvals"> = {
  profile: "/api/v1/org/settings/profile",
  security: "/api/v1/org/settings/security",
  reconciliation: "/api/v1/org/settings/reconciliation",
  approvals: "/api/v1/org/settings/approvals",
};

/** Editable org settings with ETag/If-Match and server-side validation as the authority. */
export function SettingsForm({ section, title, fields, intro }: { section: Section; title: string; fields: FieldDef[]; intro?: ReactNode }) {
  const query = useOrg();
  return (
    <Card title={title}>
      {intro ? <div className="mb-4 text-sm text-muted">{intro}</div> : null}
      <QueryState query={query}>{(v) => <Editor key={v.etag} section={section} org={v.data} etag={v.etag} fields={fields} />}</QueryState>
    </Card>
  );
}

function initial(org: Org, f: FieldDef): string | boolean {
  const value = org[f.name];
  if (f.kind === "bool") return Boolean(value);
  if (f.kind === "list") return Array.isArray(value) ? value.join(", ") : "";
  return value === null || value === undefined ? "" : String(value);
}

function Editor({ section, org, etag, fields }: { section: Section; org: Org; etag: string; fields: FieldDef[] }) {
  const qc = useQueryClient();
  const stepUp = useStepUp();
  const [values, setValues] = useState<Record<string, string | boolean>>(() => Object.fromEntries(fields.map((f) => [f.name, initial(org, f)])));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setErrors({});
    const body: Record<string, unknown> = {};
    for (const f of fields) {
      const v = values[f.name];
      if (f.kind === "bool") body[f.name] = v;
      else if (f.kind === "integer") body[f.name] = v === "" ? null : Number.parseInt(String(v), 10);
      else if (f.kind === "list") body[f.name] = String(v).split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
      else body[f.name] = v === "" ? null : String(v).trim(); // decimals stay strings
    }
    try {
      await stepUp(async () => unwrap(await api.PATCH(PATHS[section], { body: body as never, headers: { "If-Match": etag } })));
      toast.success("Settings saved");
      await qc.invalidateQueries({ queryKey: ORG_KEY });
      await qc.invalidateQueries({ queryKey: ["session"] });
    } catch (e) {
      if (isConflict(e)) setConflict(true);
      else {
        setErrors(e instanceof ApiError ? e.fieldErrors() : {});
        toast.error(errorMessage(e));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="flex max-w-xl flex-col gap-4" onSubmit={(e) => { e.preventDefault(); void save(); }} noValidate>
      {conflict ? (
        <Notice tone="warning" title="Someone else changed these settings" action={<Button size="sm" variant="secondary" onClick={() => void qc.invalidateQueries({ queryKey: ORG_KEY })}>Reload</Button>}>
          Reload to see the latest values, then make your change again.
        </Notice>
      ) : null}
      {fields.map((f) => {
        const id = `setting-${f.name}`;
        const err = errors[f.name];
        if (f.kind === "bool") {
          return (
            <div key={f.name}>
              <Checkbox id={id} label={f.label} checked={Boolean(values[f.name])} onChange={(e) => setValues({ ...values, [f.name]: e.target.checked })} />
              {f.hint ? <p className="mt-1 ml-6 text-xs text-muted">{f.hint}</p> : null}
            </div>
          );
        }
        return (
          <Field key={f.name} id={id} label={f.label} hint={f.hint} error={err}>
            {f.kind === "select" ? (
              <Select id={id} value={String(values[f.name])} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
                {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </Select>
            ) : (
              <Input id={id} inputMode={f.kind === "text" || f.kind === "list" ? undefined : "decimal"} value={String(values[f.name])} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} aria-invalid={!!err} />
            )}
          </Field>
        );
      })}
      <div><Button type="submit" loading={saving}>Save changes</Button></div>
    </form>
  );
}
