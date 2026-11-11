"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { useStepUp } from "@/components/step-up";
import { StatusBadge } from "@/components/ui/finance";
import { Button, Card, Field, Input, Select, describedBy } from "@/components/ui/core";
import { ConfirmDialog } from "@/components/ui/overlay";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";
import { applyServerErrors, zodResolver } from "@/lib/forms";
import { can, useSession } from "@/lib/session";

const ROLES = [
  { value: "viewer", label: "Viewer — read-only, can export" },
  { value: "analyst", label: "Analyst — imports, runs, claims, agreement drafts" },
  { value: "admin", label: "Admin — users, settings, approvals" },
  { value: "owner", label: "Owner — everything incl. ownership and deletion" },
] as const;
type Role = (typeof ROLES)[number]["value"];

export default function MembersPage() {
  const session = useSession();
  const isOwner = can(session, "manage_owners");
  const roles = ROLES.filter((r) => isOwner || r.value !== "owner");
  return (
    <div className="flex flex-col gap-6">
      <InviteCard roles={roles} />
      <MembersCard roles={roles} isOwner={isOwner} />
      <PendingInvites />
    </div>
  );
}

function InviteCard({ roles }: { roles: readonly { value: Role; label: string }[] }) {
  const qc = useQueryClient();
  const schema = z.object({ email: z.string().trim().email("Enter a valid email address."), role: z.enum(["viewer", "analyst", "admin", "owner"]) });
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema), defaultValues: { role: "analyst" } });
  const onSubmit = form.handleSubmit(async (body) => {
    try {
      unwrap(await api.POST("/api/v1/org/invites", { body }));
      toast.success(`Invitation sent to ${body.email}`);
      form.reset({ email: "", role: body.role });
      void qc.invalidateQueries({ queryKey: ["invites"] });
    } catch (e) {
      const msg = applyServerErrors(e, form.setError, ["email", "role"]);
      if (msg) toast.error(msg);
    }
  });
  const e = form.formState.errors;
  return (
    <Card title="Invite someone">
      <form onSubmit={onSubmit} noValidate className="grid max-w-2xl grid-cols-1 items-end gap-4 sm:grid-cols-[1fr_1fr_auto]">
        <Field id="invite-email" label="Work email" error={e.email?.message}>
          <Input id="invite-email" type="email" aria-invalid={!!e.email} aria-describedby={describedBy("invite-email", e.email?.message)} {...form.register("email")} />
        </Field>
        <Field id="invite-role" label="Role">
          <Select id="invite-role" {...form.register("role")}>
            {roles.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </Select>
        </Field>
        <Button type="submit" loading={form.formState.isSubmitting}>Send invite</Button>
      </form>
    </Card>
  );
}

function MembersCard({ roles, isOwner }: { roles: readonly { value: Role; label: string }[]; isOwner: boolean }) {
  const session = useSession();
  const qc = useQueryClient();
  const stepUp = useStepUp();
  const [confirm, setConfirm] = useState<{ id: string; email: string; active: boolean } | null>(null);
  const query = useQuery({ queryKey: ["members"], queryFn: async () => unwrap(await api.GET("/api/v1/org/members")) });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["members"] });
  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: Role }) => stepUp(async () => unwrap(await api.PATCH("/api/v1/org/members/{membership_id}", { params: { path: { membership_id: id } }, body: { role } }))),
    onSuccess: () => { toast.success("Role changed"); refresh(); },
    onError: (e) => { toast.error(errorMessage(e)); refresh(); },
  });
  const setStatus = useMutation({
    mutationFn: async ({ id, active }: { id: string; active: boolean }) =>
      unwrap(active
        ? await api.POST("/api/v1/org/members/{membership_id}/reactivate", { params: { path: { membership_id: id } } })
        : await api.POST("/api/v1/org/members/{membership_id}/deactivate", { params: { path: { membership_id: id } } })),
    onSuccess: () => { setConfirm(null); toast.success("Member updated"); refresh(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Members">
      <QueryState query={query} isEmpty={(m) => m.length === 0} empty={<EmptyState title="No members yet" />}>
        {(members) => (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" aria-label="Members">
              <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th className="py-2">Person</th><th>Role</th><th>Status</th><th>Joined</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {members.map((m) => {
                  const self = m.user_id === session.user?.id;
                  const locked = (m.role === "owner" && !isOwner) || self;
                  return (
                    <tr key={m.id} className="border-b border-rule last:border-0">
                      <td className="py-2"><p className="font-medium">{m.name || m.email}</p><p className="text-xs text-muted">{m.email}{self ? " (you)" : ""}</p></td>
                      <td>
                        <label htmlFor={`role-${m.id}`} className="sr-only">Role of {m.email}</label>
                        <Select id={`role-${m.id}`} value={m.role} disabled={locked || changeRole.isPending} className="h-8 max-w-40" onChange={(e) => changeRole.mutate({ id: m.id, role: e.target.value as Role })}>
                          {(locked ? ROLES : roles).map((r) => <option key={r.value} value={r.value}>{r.value[0].toUpperCase() + r.value.slice(1)}</option>)}
                        </Select>
                      </td>
                      <td><StatusBadge status={m.status} /></td>
                      <td>{formatDate(m.created_at.slice(0, 10))}</td>
                      <td className="text-right">
                        {!locked ? (
                          <Button variant="ghost" size="sm" onClick={() => setConfirm({ id: m.id, email: m.email, active: m.status !== "active" })}>
                            {m.status === "active" ? "Deactivate" : "Reactivate"}
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </QueryState>
      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(o) => !o && setConfirm(null)}
        title={confirm?.active ? `Reactivate ${confirm.email}?` : `Deactivate ${confirm?.email}?`}
        description={confirm?.active ? "They regain access with their previous role." : "They are signed out of this organization immediately. Their work stays in the history."}
        confirmLabel={confirm?.active ? "Reactivate" : "Deactivate"}
        tone={confirm?.active ? "primary" : "danger"}
        pending={setStatus.isPending}
        onConfirm={() => confirm && setStatus.mutate({ id: confirm.id, active: confirm.active })}
      />
    </Card>
  );
}

function PendingInvites() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["invites"], queryFn: async () => unwrap(await api.GET("/api/v1/org/invites")) });
  const act = useMutation({
    mutationFn: async ({ id, action }: { id: string; action: "resend" | "revoke" }) => {
      if (action === "resend") unwrap(await api.POST("/api/v1/org/invites/{invite_id}/resend", { params: { path: { invite_id: id } } }));
      else unwrap(await api.DELETE("/api/v1/org/invites/{invite_id}", { params: { path: { invite_id: id } } }));
    },
    onSuccess: (_, v) => { toast.success(v.action === "resend" ? "Invitation sent again" : "Invitation revoked"); void qc.invalidateQueries({ queryKey: ["invites"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Pending invitations">
      <QueryState query={query} isEmpty={(i) => i.length === 0} empty={<p className="text-sm text-muted">No pending invitations.</p>}>
        {(invites) => (
          <ul className="divide-y divide-rule">
            {invites.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm">
                <span><strong>{i.email}</strong> as <span className="capitalize">{i.role}</span> · expires {formatDateTime(i.expires_at)}</span>
                <span className="flex gap-2">
                  <Button variant="secondary" size="sm" onClick={() => act.mutate({ id: i.id, action: "resend" })}>Resend</Button>
                  <Button variant="ghost" size="sm" onClick={() => act.mutate({ id: i.id, action: "revoke" })}>Revoke</Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </Card>
  );
}
