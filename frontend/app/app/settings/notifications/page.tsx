"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Card } from "@/components/ui/core";
import { QueryState } from "@/components/ui/states";
import { api, errorMessage, unwrap } from "@/lib/api";

export default function NotificationSettings() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["notification-preferences"], queryFn: async () => unwrap(await api.GET("/api/v1/notification-preferences")) });
  const save = useMutation({
    mutationFn: async (body: { type: string; in_app?: boolean; email?: boolean }) => unwrap(await api.PUT("/api/v1/notification-preferences", { body })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["notification-preferences"] }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  return (
    <Card title="Notifications">
      <p className="mb-4 text-sm text-muted">Choose how you hear about alerts. Security and account emails (sign-ins, password and MFA changes) always send.</p>
      <QueryState query={query}>
        {(prefs) => (
          <table className="w-full max-w-2xl text-sm" aria-label="Notification preferences">
            <thead><tr className="border-b border-rule text-left text-xs text-muted uppercase"><th className="py-2">Alert</th><th className="text-center">In app</th><th className="text-center">Email</th></tr></thead>
            <tbody>
              {prefs.map((p) => (
                <tr key={p.type} className="border-b border-rule last:border-0">
                  <td className="py-2">{p.label}</td>
                  <td className="text-center"><input type="checkbox" aria-label={`${p.label} in app`} checked={p.in_app} disabled={save.isPending} onChange={(e) => save.mutate({ type: p.type, in_app: e.target.checked })} /></td>
                  <td className="text-center"><input type="checkbox" aria-label={`${p.label} by email`} checked={p.email} disabled={save.isPending} onChange={(e) => save.mutate({ type: p.type, email: e.target.checked })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
    </Card>
  );
}
