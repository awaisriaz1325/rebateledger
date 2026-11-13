"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Card, Input } from "@/components/ui/core";
import { ConfirmDialog } from "@/components/ui/overlay";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDate } from "@/lib/format";

export default function TemplatesSettings() {
  const qc = useQueryClient();
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [archiving, setArchiving] = useState<{ id: string; name: string } | null>(null);
  const query = useQuery({ queryKey: ["import-templates"], queryFn: async () => unwrap(await api.GET("/api/v1/import-templates")) });
  const patch = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: { name?: string; is_default?: boolean; archived?: boolean } }) =>
      unwrap(await api.PATCH("/api/v1/import-templates/{template_id}", { params: { path: { template_id: id } }, body })),
    onSuccess: () => { setRenaming(null); setArchiving(null); void qc.invalidateQueries({ queryKey: ["import-templates"] }); toast.success("Template updated"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="flex flex-col gap-6">
    <Card title="Import mapping templates">
      <p className="mb-4 text-sm text-muted">Templates remember column mappings and formats. Save one from the last step of an import. The default template is applied automatically to new uploads of that type.</p>
      <QueryState query={query} isEmpty={(t) => t.length === 0} empty={<EmptyState title="No templates yet">Finish an import and choose “Save as template”.</EmptyState>}>
        {(templates) => (
          <table className="w-full text-sm" aria-label="Import templates">
            <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th className="py-2">Name</th><th>Type</th><th>Version</th><th>Saved</th><th>Default</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {templates.map((t) => (
                <tr key={t.id} className="border-b border-rule last:border-0">
                  <td className="py-2">
                    {renaming?.id === t.id ? (
                      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); patch.mutate({ id: t.id, body: { name: renaming.name } }); }}>
                        <label htmlFor={`rename-${t.id}`} className="sr-only">New name</label>
                        <Input id={`rename-${t.id}`} className="h-8" value={renaming.name} onChange={(e) => setRenaming({ id: t.id, name: e.target.value })} autoFocus />
                        <Button size="sm" type="submit">Save</Button>
                      </form>
                    ) : t.name}
                  </td>
                  <td className="capitalize">{t.import_type}</td>
                  <td>v{t.version}</td>
                  <td>{formatDate(t.created_at.slice(0, 10))}</td>
                  <td>{t.is_default ? <span className="text-positive font-medium">Default</span> : <Button variant="ghost" size="sm" onClick={() => patch.mutate({ id: t.id, body: { is_default: true } })}>Make default</Button>}</td>
                  <td className="text-right whitespace-nowrap">
                    <Button variant="ghost" size="sm" onClick={() => setRenaming({ id: t.id, name: t.name })}>Rename</Button>
                    <Button variant="ghost" size="sm" onClick={() => setArchiving({ id: t.id, name: t.name })}>Delete</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
      <ConfirmDialog open={archiving !== null} onOpenChange={(o) => !o && setArchiving(null)} title={`Delete template “${archiving?.name}”?`} description="Past imports keep their settings; the template is no longer offered." confirmLabel="Delete" pending={patch.isPending} onConfirm={() => archiving && patch.mutate({ id: archiving.id, body: { archived: true } })} />
    </Card>
    <ErpPresets />
    </div>
  );
}

/** Read-only ERP report presets (v1.1 Phase 12): copy one to make an editable template. */
function ErpPresets() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["import-presets", "all"], queryFn: async () => unwrap(await api.GET("/api/v1/import-presets")) });
  const copy = useMutation({
    mutationFn: async ({ id, name }: { id: string; name: string }) =>
      unwrap(await api.POST("/api/v1/import-templates/from-preset", { body: { preset_id: id, name, is_default: false } })),
    onSuccess: (t) => { void qc.invalidateQueries({ queryKey: ["import-templates"] }); toast.success(`Saved as template “${t.name}”`); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="ERP report presets">
      <p className="mb-4 text-sm text-muted">
        Starting points for common ERP exports. They are best guesses that have not yet been checked against a real export, and ERPs let you change report columns, so always check the mapping. Copy one to make your own editable template.
      </p>
      <QueryState query={query} isEmpty={(p) => p.length === 0} empty={<EmptyState title="No presets">There are no ERP presets.</EmptyState>}>
        {(presets) => (
          <table className="w-full text-sm" aria-label="ERP report presets">
            <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th className="py-2">ERP</th><th>Report</th><th>Type</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {presets.map((p) => (
                <tr key={p.id} className="border-b border-rule last:border-0">
                  <td className="py-2 font-medium">{p.erp}</td>
                  <td>{p.report}{p.notes ? <span className="block text-xs text-muted">{p.notes}</span> : null}</td>
                  <td className="capitalize">{p.import_type}</td>
                  <td>{p.verified ? <span className="text-positive font-medium">Verified</span> : <span className="text-warning">Unverified</span>}</td>
                  <td className="text-right whitespace-nowrap">
                    <a className="mr-2 text-sm text-brand underline" href={`/api/v1/import-presets/header.csv?preset_id=${encodeURIComponent(p.id)}`} download>
                      Header row<span className="sr-only"> for {p.erp} {p.import_type}</span>
                    </a>
                    <Button variant="ghost" size="sm" loading={copy.isPending && copy.variables?.id === p.id} onClick={() => copy.mutate({ id: p.id, name: `${p.erp} ${p.import_type}` })}>
                      Copy to my templates<span className="sr-only"> ({p.erp} {p.import_type})</span>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
    </Card>
  );
}
