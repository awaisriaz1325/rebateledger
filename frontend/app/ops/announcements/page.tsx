"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Card, Field, Input, PageHeader, Select } from "@/components/ui/core";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export default function OpsAnnouncementsPage() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["ops", "announcements"], queryFn: async () => unwrap(await api.GET("/api/v1/ops/announcements")) });
  const [f, setF] = useState({ message: "", level: "info" as "info" | "warning", ends_at: "" });
  const refresh = () => qc.invalidateQueries({ queryKey: ["ops", "announcements"] });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/ops/announcements", { body: { message: f.message, level: f.level, ends_at: f.ends_at ? new Date(f.ends_at).toISOString() : null } })),
    onSuccess: () => { toast.success("Announcement published"); setF({ message: "", level: "info", ends_at: "" }); void refresh(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const end = useMutation({
    mutationFn: async ({ id, message, level }: { id: string; message: string; level: "info" | "warning" }) => unwrap(await api.PATCH("/api/v1/ops/announcements/{announcement_id}", { params: { path: { announcement_id: id } }, body: { message, level, ends_at: new Date().toISOString() } })),
    onSuccess: () => void refresh(),
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <>
      <PageHeader title="Announcements" description="A banner shown to every signed-in user, e.g. planned maintenance." />
      <Card title="New announcement">
        <form className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[1fr_140px_220px_auto]" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <Field id="a-msg" label="Message"><Input id="a-msg" value={f.message} maxLength={500} onChange={(e) => setF({ ...f, message: e.target.value })} /></Field>
          <Field id="a-level" label="Style"><Select id="a-level" value={f.level} onChange={(e) => setF({ ...f, level: e.target.value as "info" | "warning" })}><option value="info">Information</option><option value="warning">Warning</option></Select></Field>
          <Field id="a-end" label="Ends (optional)"><Input id="a-end" type="datetime-local" value={f.ends_at} onChange={(e) => setF({ ...f, ends_at: e.target.value })} /></Field>
          <Button type="submit" loading={create.isPending} disabled={!f.message.trim()}>Publish</Button>
        </form>
      </Card>
      <div className="mt-6">
        <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title="No announcements" />}>
          {(rows) => (
            <ul className="divide-y divide-rule rounded-lg border border-rule bg-surface text-sm">
              {rows.map((a) => {
                const live = !a.ends_at || new Date(a.ends_at) > new Date();
                return (
                  <li key={a.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                    <div><p>{a.message}</p><p className="text-xs text-muted">{a.level} · from {formatDateTime(a.starts_at)}{a.ends_at ? ` until ${formatDateTime(a.ends_at)}` : ""}</p></div>
                    {live ? <Button size="sm" variant="secondary" onClick={() => end.mutate({ id: a.id, message: a.message, level: a.level === "warning" ? "warning" : "info" })}>End now</Button> : <span className="text-xs text-muted">Ended</span>}
                  </li>
                );
              })}
            </ul>
          )}
        </QueryState>
      </div>
    </>
  );
}
