"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { SettingsForm } from "@/components/settings-form";
import { useStepUp } from "@/components/step-up";
import { Button, Card, Field, Input, Select } from "@/components/ui/core";
import { ConfirmDialog } from "@/components/ui/overlay";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { can, useSession } from "@/lib/session";

export default function SecuritySettings() {
  const session = useSession();
  return (
    <div className="flex flex-col gap-6">
      <SettingsForm
        section="security"
        title="Security policy"
        intro="Changing security settings asks you to confirm your password."
        fields={[
          { name: "require_mfa_all", label: "Require two-factor authentication for everyone", kind: "bool", hint: "Owners and Admins always need it." },
          { name: "session_idle_minutes", label: "Sign out after inactivity (minutes, 15–240)", kind: "integer" },
          { name: "allowed_invite_domains", label: "Allowed invite domains (comma-separated, optional)", kind: "list", hint: "For example acme.com, acme-supply.com. Empty allows any domain." },
        ]}
      />
      {can(session, "manage_support_access") ? <SupportAccess /> : null}
    </div>
  );
}

function SupportAccess() {
  const qc = useQueryClient();
  const stepUp = useStepUp();
  const [hours, setHours] = useState("24");
  const [scope, setScope] = useState<"read_only" | "read_write">("read_only");
  const [reason, setReason] = useState("");
  const [revoking, setRevoking] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["support-access"], queryFn: async () => unwrap(await api.GET("/api/v1/org/support-access")) });
  const grant = useMutation({
    mutationFn: () => stepUp(async () => unwrap(await api.POST("/api/v1/org/support-access", { body: { hours: Number.parseInt(hours, 10), scope, reason } }))),
    onSuccess: () => {
      toast.success("Support access granted");
      void qc.invalidateQueries({ queryKey: ["support-access"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const revoke = useMutation({
    mutationFn: async (id: string) => unwrap(await api.DELETE("/api/v1/org/support-access/{grant_id}", { params: { path: { grant_id: id } } })),
    onSuccess: () => {
      setRevoking(null);
      toast.success("Support access revoked");
      void qc.invalidateQueries({ queryKey: ["support-access"] });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Support access">
      <p className="mb-4 text-sm text-muted">Let the support team see this organization for a limited time. Everything they do is recorded in the audit log, and everyone in your organization sees a banner while access is active.</p>
      <QueryState query={query} isEmpty={(g) => g.length === 0} empty={<EmptyState title="No active support access" />}>
        {(grants) => (
          <ul className="mb-4 divide-y divide-rule">
            {grants.map((g) => (
              <li key={g.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span>{g.scope === "read_only" ? "Read-only" : "Read-write"} until {formatDateTime(g.expires_at)}{g.reason ? ` — ${g.reason}` : ""}</span>
                <Button variant="secondary" size="sm" onClick={() => setRevoking(g.id)}>Revoke</Button>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
      <form className="mt-4 grid max-w-xl grid-cols-1 gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); grant.mutate(); }}>
        <Field id="sa-hours" label="Duration">
          <Select id="sa-hours" value={hours} onChange={(e) => setHours(e.target.value)}>
            <option value="4">4 hours</option><option value="24">24 hours</option><option value="72">3 days</option><option value="168">7 days (maximum)</option>
          </Select>
        </Field>
        <Field id="sa-scope" label="Scope">
          <Select id="sa-scope" value={scope} onChange={(e) => setScope(e.target.value as "read_only" | "read_write")}>
            <option value="read_only">Read-only (recommended)</option><option value="read_write">Read-write</option>
          </Select>
        </Field>
        <Field id="sa-reason" label="Reason (optional)" className="sm:col-span-2">
          <Input id="sa-reason" maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <div><Button type="submit" loading={grant.isPending}>Grant access</Button></div>
      </form>
      <ConfirmDialog open={revoking !== null} onOpenChange={(o) => !o && setRevoking(null)} title="Revoke support access?" description="The support team loses access immediately." confirmLabel="Revoke" pending={revoke.isPending} onConfirm={() => revoking && revoke.mutate(revoking)} />
    </Card>
  );
}
