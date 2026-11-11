"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Field, PageHeader, Textarea } from "@/components/ui/core";
import { StatusBadge } from "@/components/ui/finance";
import { Dialog, Tabs } from "@/components/ui/overlay";
import { EmptyState, QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { can, useSession } from "@/lib/session";
import type { Approval } from "@/lib/types";

type Status = "pending" | "approved" | "rejected" | "cancelled";

export default function ApprovalsPage() {
  return (
    <>
      <PageHeader title="Approvals" description="Four-eyes checks: agreement activations and claim write-offs need a second person. Nobody can approve their own request." />
      <Tabs
        label="Approval status"
        tabs={(["pending", "approved", "rejected", "cancelled"] as const).map((s) => ({ value: s, label: s[0].toUpperCase() + s.slice(1), content: <ApprovalList status={s} /> }))}
      />
    </>
  );
}

function ApprovalList({ status }: { status: Status }) {
  const session = useSession();
  const members = useQuery({ queryKey: ["members"], queryFn: async () => unwrap(await api.GET("/api/v1/org/members")) });
  const people = new Map((members.data ?? []).map((m) => [m.user_id, m.name]));
  const query = useQuery({ queryKey: ["approvals", status], queryFn: async () => unwrap(await api.GET("/api/v1/approvals", { params: { query: { status } } })) });
  const [deciding, setDeciding] = useState<{ a: Approval; decision: "approve" | "reject" } | null>(null);
  const me = session.user?.id;
  return (
    <>
      <QueryState query={query} isEmpty={(r) => r.length === 0} empty={<EmptyState title={status === "pending" ? "Nothing waiting for approval" : `No ${status} requests`} />}>
        {(rows) => (
          <ul className="flex flex-col gap-3">
            {rows.map((a) => {
              const own = a.requested_by === me;
              return (
                <li key={a.id} className="rounded-lg border border-rule bg-surface p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-medium">{a.link ? <Link href={a.link} className="hover:underline">{a.label || "Request"}</Link> : a.label || "Request"}</p>
                      <p className="text-xs text-muted">Requested by {people.get(a.requested_by) ?? "a team member"} · {formatDateTime(a.requested_at)}</p>
                      {a.request_note ? <p className="mt-2 text-sm whitespace-pre-wrap">“{a.request_note}”</p> : null}
                      {a.decided_at ? <p className="mt-2 text-xs text-muted">Decided by {a.decided_by ? people.get(a.decided_by) ?? "a team member" : "—"} · {formatDateTime(a.decided_at)}{a.decision_note ? ` — “${a.decision_note}”` : ""}</p> : null}
                    </div>
                    <StatusBadge status={a.status} />
                  </div>
                  {status === "pending" && can(session, "approve") ? (
                    own ? <p className="mt-3 text-xs text-muted">You requested this, so someone else must decide.</p> : (
                      <div className="mt-3 flex gap-2">
                        <Button size="sm" onClick={() => setDeciding({ a, decision: "approve" })}>Approve</Button>
                        <Button size="sm" variant="secondary" onClick={() => setDeciding({ a, decision: "reject" })}>Reject</Button>
                      </div>
                    )
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </QueryState>
      {deciding ? <Decide approval={deciding.a} decision={deciding.decision} onClose={() => setDeciding(null)} /> : null}
    </>
  );
}

function Decide({ approval, decision, onClose }: { approval: Approval; decision: "approve" | "reject"; onClose: () => void }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/approvals/{approval_id}/decision", { params: { path: { approval_id: approval.id } }, body: { decision, note } })),
    onSuccess: async () => {
      toast.success(decision === "approve" ? "Approved" : "Rejected");
      await qc.invalidateQueries();
      onClose();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={decision === "approve" ? "Approve this request?" : "Reject this request?"}
      description={approval.label}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant={decision === "reject" ? "danger" : "primary"} loading={decide.isPending} onClick={() => decide.mutate()}>{decision === "approve" ? "Approve" : "Reject"}</Button></>}
    >
      {approval.link ? <p className="mb-3 text-sm"><Link href={approval.link} className="text-brand underline">Review the details first</Link></p> : null}
      <Field id="decision-note" label="Note (optional)"><Textarea id="decision-note" rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
    </Dialog>
  );
}
