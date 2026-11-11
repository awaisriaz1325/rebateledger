"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { ExplainBody } from "@/components/explain-drawer";
import { TermsEditor, useTermsValid } from "@/components/terms-editor";
import { Button, Card, Field, Input, Notice, PageHeader, Select } from "@/components/ui/core";
import { DateText, StatusBadge } from "@/components/ui/finance";
import { ConfirmDialog, Dialog, Tabs } from "@/components/ui/overlay";
import { QueryState } from "@/components/ui/states";
import { ApiError, api, errorMessage, unwrap, uploadForm } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { can, useSession } from "@/lib/session";
import type { AgreementDetail, Terms, Version } from "@/lib/types";
import type { components } from "@/generated/api";

type AttachmentOut = components["schemas"]["AttachmentOut"];

export default function AgreementPage() {
  const { id } = useParams<{ id: string }>();
  const query = useQuery({
    queryKey: ["agreement", id],
    queryFn: async () => unwrap(await api.GET("/api/v1/agreements/{agreement_id}", { params: { path: { agreement_id: id } } })),
  });
  return <QueryState query={query}>{(a) => <Agreement a={a} />}</QueryState>;
}

function Agreement({ a }: { a: AgreementDetail }) {
  const session = useSession();
  const qc = useQueryClient();
  const versions = [...a.versions].sort((x, y) => y.version_no - x.version_no);
  const [selected, setSelected] = useState(versions[0]?.id);
  const [newVersion, setNewVersion] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const v = versions.find((x) => x.id === selected) ?? versions[0];
  const editable = can(session, "edit_agreements");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["agreement", a.id] });
  const archive = useMutation({
    mutationFn: async () => unwrap(a.status === "archived"
      ? await api.POST("/api/v1/agreements/{agreement_id}/unarchive", { params: { path: { agreement_id: a.id } } })
      : await api.POST("/api/v1/agreements/{agreement_id}/archive", { params: { path: { agreement_id: a.id } } })),
    onSuccess: () => { setArchiving(false); refresh(); toast.success(a.status === "archived" ? "Agreement restored" : "Agreement archived"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const hasDraft = versions.some((x) => x.status === "draft" || x.status === "pending_approval");
  return (
    <>
      <PageHeader
        title={a.name}
        description={<>{a.external_reference ? <span className="font-mono text-xs">{a.external_reference} · </span> : null}{a.summary}</>}
        actions={editable ? (
          <>
            {!hasDraft && a.status !== "archived" ? <Button onClick={() => setNewVersion(true)}>New version</Button> : null}
            <Button variant="secondary" onClick={() => setArchiving(true)}>{a.status === "archived" ? "Unarchive" : "Archive"}</Button>
          </>
        ) : undefined}
      >
        <div className="mt-2"><StatusBadge status={a.status} /></div>
      </PageHeader>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[240px_1fr]">
        <nav aria-label="Versions">
          <h2 className="mb-2 text-xs font-semibold text-muted uppercase">Versions</h2>
          <ul className="flex flex-col gap-1">
            {versions.map((x) => (
              <li key={x.id}>
                <button type="button" onClick={() => setSelected(x.id)} aria-current={x.id === v?.id ? "true" : undefined}
                  className={`w-full rounded-md border px-3 py-2 text-left text-sm ${x.id === v?.id ? "border-brand bg-brand-soft" : "border-rule bg-surface hover:bg-surface-2"}`}>
                  <span className="flex items-center justify-between gap-2"><strong>v{x.version_no}</strong><StatusBadge status={x.status} /></span>
                  <span className="mt-1 block text-xs text-muted"><DateText value={x.effective_from} /> – {x.effective_to ? <DateText value={x.effective_to} /> : "open"}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>
        {v ? (
          <Tabs
            key={v.id}
            label="Version"
            tabs={[
              { value: "terms", label: "Terms", content: <VersionTerms version={v} editable={editable} onChanged={refresh} /> },
              { value: "preview", label: "Preview", content: <Preview version={v} /> },
              { value: "history", label: "Compare versions", content: <Compare versions={versions} /> },
              { value: "files", label: "Documents", content: <Attachments agreementId={a.id} editable={editable} /> },
            ]}
          />
        ) : null}
      </div>
      <NewVersionDialog open={newVersion} onOpenChange={setNewVersion} agreementId={a.id} base={versions[0]} onCreated={(nv) => { refresh(); setSelected(nv.id); }} />
      <ConfirmDialog open={archiving} onOpenChange={setArchiving} title={a.status === "archived" ? "Unarchive agreement?" : "Archive agreement?"}
        description={a.status === "archived" ? "It will be included in runs again." : "Archived agreements are left out of new runs. Past results stay."} confirmLabel={a.status === "archived" ? "Unarchive" : "Archive"} tone={a.status === "archived" ? "primary" : "danger"} pending={archive.isPending} onConfirm={() => archive.mutate()} />
    </>
  );
}

function VersionTerms({ version, editable, onChanged }: { version: Version; editable: boolean; onChanged: () => void }) {
  const session = useSession();
  const [terms, setTerms] = useState<Terms>(version.terms);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [note, setNote] = useState("");
  const valid = useTermsValid(terms);
  const isDraft = version.status === "draft";
  const save = useMutation({
    mutationFn: async () => {
      const head = await api.GET("/api/v1/agreement-versions/{version_id}", { params: { path: { version_id: version.id } } });
      return unwrap(await api.PUT("/api/v1/agreement-versions/{version_id}", { params: { path: { version_id: version.id } }, body: terms, headers: { "If-Match": head.response.headers.get("ETag") ?? "" } }));
    },
    onSuccess: () => { setEditing(false); toast.success("Draft saved"); onChanged(); },
    onError: (e) => toast.error(e instanceof ApiError && e.status === 412 ? "Someone else changed this draft. Reload and try again." : errorMessage(e)),
  });
  const activate = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/agreement-versions/{version_id}/activate", { params: { path: { version_id: version.id } }, body: { note } })),
    onSuccess: (r) => { toast.success(r.status === "pending_approval" ? "Sent for approval" : "Version activated"); onChanged(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: async () => unwrap(await api.DELETE("/api/v1/agreement-versions/{version_id}", { params: { path: { version_id: version.id } } })),
    onSuccess: () => { setConfirmDelete(false); onChanged(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <div className="flex flex-col gap-4">
      <Card title={`Version ${version.version_no}`} actions={<StatusBadge status={version.status} />}>
        <p className="text-sm leading-relaxed">{version.summary}</p>
        <p className="mt-2 text-xs text-muted">Created {formatDateTime(version.created_at)}{version.activated_at ? ` · activated ${formatDateTime(version.activated_at)}` : ""}</p>
        {version.status === "active" || version.status === "superseded" ? <p className="mt-2 text-xs text-muted">This version is locked. To change terms, create a new version with an effective date.</p> : null}
        {version.status === "pending_approval" ? <div className="mt-3"><Notice tone="warning">Awaiting approval by a different Admin or Owner.</Notice></div> : null}
        {isDraft && editable ? (
          <div className="mt-4 flex flex-wrap items-end gap-2">
            {!editing ? <Button variant="secondary" onClick={() => setEditing(true)}>Edit draft</Button> : null}
            {can(session, "activate_agreements") ? (
              <>
                <Field id="act-note" label="Note for approver (optional)" className="min-w-64"><Input id="act-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} /></Field>
                <Button onClick={() => activate.mutate()} loading={activate.isPending} disabled={editing}>Activate</Button>
              </>
            ) : null}
            <Button variant="ghost" onClick={() => setConfirmDelete(true)}>Delete draft</Button>
          </div>
        ) : null}
      </Card>
      {editing ? (
        <>
          <TermsEditor value={terms} onChange={setTerms} />
          <div className="flex gap-2"><Button onClick={() => save.mutate()} loading={save.isPending} disabled={valid !== true}>Save draft</Button><Button variant="secondary" onClick={() => { setTerms(version.terms); setEditing(false); }}>Cancel</Button></div>
        </>
      ) : (
        <TermsTable terms={version.terms} />
      )}
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} title="Delete this draft?" description="The draft and its terms are removed." confirmLabel="Delete" pending={remove.isPending} onConfirm={() => remove.mutate()} />
    </div>
  );
}

/** Flat key → value view of terms, used for display and for side-by-side diffs. */
function flattenTerms(t: Terms): [string, string][] {
  const rows: [string, string][] = [
    ["Effective", `${t.effective_from} – ${t.effective_to ?? "open"}`],
    ["Period", `${t.period_type}${t.fiscal_aligned ? " (fiscal)" : ""}`],
    ["Date basis", t.date_basis], ["Measure", t.measure], ["Returns", t.spend_basis], ["Threshold comparison", t.threshold_comparison],
    ["Negative result", t.negative_result], ["Rounding", t.rounding_mode], ["Payment terms (days)", String(t.payment_terms_days)], ["Stacking", t.stacking],
    ["Prorate partial periods", t.prorate_thresholds_on_partial_period ? "yes" : "no"], ["Zero baseline", t.zero_baseline_policy],
    ["Cap", t.cap_amount ?? "none"], ["Minimum payout", t.minimum_payout ?? "none"],
  ];
  t.components.forEach((c, i) => {
    const parts = [c.type, c.rate && `rate ${c.rate}`, c.amount_per_unit && `per unit ${c.amount_per_unit}`, c.amount && `bonus ${c.amount}`, c.threshold && `at ${c.threshold}`, c.growth_pct && `growth ${c.growth_pct}`, c.baseline_source, c.prior_period_offset].filter(Boolean);
    rows.push([`Component ${i + 1} (${c.key})`, parts.join(", ")]);
    (c.tiers ?? []).forEach((tier, ti) => rows.push([`  Tier ${ti + 1}`, `from ${tier.threshold}: ${tier.rate != null ? `rate ${tier.rate}` : `per unit ${tier.amount_per_unit}`}`]));
  });
  (t.eligibility ?? []).forEach((r, i) => rows.push([`Rule ${i + 1}`, `${r.action} ${r.field} ${r.flag ?? r.min_amount ?? (r.values ?? []).join(", ")}`]));
  return rows;
}

function TermsTable({ terms }: { terms: Terms }) {
  return (
    <Card title="Terms">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-[240px_1fr]">
        {flattenTerms(terms).map(([k, val], i) => <div key={i} className="contents"><dt className="text-muted">{k}</dt><dd className="font-mono text-xs leading-6">{val}</dd></div>)}
      </dl>
    </Card>
  );
}

function Compare({ versions }: { versions: Version[] }) {
  const [left, setLeft] = useState(versions[1]?.id ?? versions[0]?.id);
  const [right, setRight] = useState(versions[0]?.id);
  const a = versions.find((v) => v.id === left);
  const b = versions.find((v) => v.id === right);
  if (versions.length < 2) return <p className="text-sm text-muted">Only one version exists.</p>;
  const fa = new Map(a ? flattenTerms(a.terms) : []);
  const fb = new Map(b ? flattenTerms(b.terms) : []);
  const keys = [...new Set([...fa.keys(), ...fb.keys()])];
  return (
    <Card>
      <div className="mb-4 flex flex-wrap gap-3">
        <Field id="cmp-left" label="From"><Select id="cmp-left" value={left} onChange={(e) => setLeft(e.target.value)}>{versions.map((v) => <option key={v.id} value={v.id}>Version {v.version_no}</option>)}</Select></Field>
        <Field id="cmp-right" label="To"><Select id="cmp-right" value={right} onChange={(e) => setRight(e.target.value)}>{versions.map((v) => <option key={v.id} value={v.id}>Version {v.version_no}</option>)}</Select></Field>
      </div>
      <table className="w-full text-sm" aria-label="Differences between versions">
        <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th className="py-2">Term</th><th>Version {a?.version_no}</th><th>Version {b?.version_no}</th></tr></thead>
        <tbody>
          {keys.map((k) => {
            const changed = fa.get(k) !== fb.get(k);
            return (
              <tr key={k} className={`border-b border-rule last:border-0 ${changed ? "bg-warning-soft" : ""}`}>
                <td className="py-1.5 pr-3">{k}{changed ? <span className="sr-only"> (changed)</span> : null}</td>
                <td className="font-mono text-xs">{fa.get(k) ?? "—"}</td>
                <td className="font-mono text-xs">{fb.get(k) ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}

function Preview({ version }: { version: Version }) {
  const [date, setDate] = useState(version.effective_from);
  const preview = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/agreement-versions/{version_id}/preview", { params: { path: { version_id: version.id } }, body: { period_containing: date } })),
  });
  return (
    <Card title="Dry run against imported data">
      <p className="mb-3 text-sm text-muted">Calculates this version for one period using purchases already imported. Nothing is saved.</p>
      <form className="mb-4 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); preview.mutate(); }}>
        <Field id="pv-date" label="Period containing"><Input id="pv-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Button type="submit" loading={preview.isPending}>Preview</Button>
      </form>
      {preview.isError ? <Notice tone="negative">{errorMessage(preview.error)}</Notice> : null}
      {preview.data ? <ExplainBody r={preview.data} /> : null}
    </Card>
  );
}

function NewVersionDialog({ open, onOpenChange, agreementId, base, onCreated }: { open: boolean; onOpenChange: (o: boolean) => void; agreementId: string; base?: Version; onCreated: (v: Version) => void }) {
  const [terms, setTerms] = useState<Terms | null>(null);
  const current = terms ?? (base ? { ...base.terms, effective_from: new Date().toISOString().slice(0, 10), effective_to: null } : null);
  const valid = useTermsValid(current ?? (base?.terms as Terms));
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/agreements/{agreement_id}/versions", { params: { path: { agreement_id: agreementId } }, body: current as Terms })),
    onSuccess: (v) => { onOpenChange(false); setTerms(null); toast.success(`Version ${v.version_no} created as a draft`); onCreated(v); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!current) return null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New version" description="Starts from the latest terms. Set the date the new terms take effect; the current version ends the day before when you activate." wide
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={() => create.mutate()} loading={create.isPending} disabled={valid !== true}>Create draft</Button></>}>
      <TermsEditor value={current} onChange={setTerms} />
    </Dialog>
  );
}

function Attachments({ agreementId, editable }: { agreementId: string; editable: boolean }) {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["agreement-attachments", agreementId], queryFn: async () => unwrap(await api.GET("/api/v1/agreements/{agreement_id}/attachments", { params: { path: { agreement_id: agreementId } } })) });
  const [uploading, setUploading] = useState(false);
  async function upload(file: File) {
    setUploading(true);
    try {
      const body = new FormData();
      body.append("file", file);
      await uploadForm<AttachmentOut>(`/api/v1/agreements/${agreementId}/attachments`, body);
      toast.success("Document attached");
      void qc.invalidateQueries({ queryKey: ["agreement-attachments", agreementId] });
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setUploading(false);
    }
  }
  return (
    <Card title="Source documents">
      <QueryState query={query} isEmpty={(a) => a.length === 0} empty={<p className="mb-4 text-sm text-muted">No documents attached.</p>}>
        {(rows) => (
          <ul className="mb-4 divide-y divide-rule">
            {rows.map((r) => <li key={r.id} className="flex items-center justify-between py-2 text-sm"><a className="text-brand hover:underline" href={`/api/v1/agreement-attachments/${r.id}/download`}>{r.filename}</a><span className="text-xs text-muted">{(r.size_bytes / 1024).toFixed(0)} KB · {formatDateTime(r.created_at)}</span></li>)}
          </ul>
        )}
      </QueryState>
      {editable ? (
        <div>
          <label htmlFor="attach" className="text-sm font-medium">Attach PDF, DOCX, XLSX or image (max 20 MB)</label>
          <input id="attach" type="file" accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg" disabled={uploading} className="mt-2 block text-sm" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
        </div>
      ) : null}
    </Card>
  );
}
