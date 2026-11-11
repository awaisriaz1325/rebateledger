"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { Popover } from "radix-ui";
import Link from "next/link";
import { api, unwrap } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export function NotificationBell() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["notifications"],
    queryFn: async () => unwrap(await api.GET("/api/v1/notifications", { params: { query: { limit: 20 } } })),
    refetchInterval: 60_000,
  });
  const markAll = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/notifications/read", { body: {} })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
  const unread = query.data?.unread ?? 0;
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className="relative rounded-md p-2 hover:bg-surface-2" aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}>
          <Bell size={18} aria-hidden="true" />
          {unread ? <span className="absolute top-1 right-1 min-w-4 rounded-full bg-negative px-1 text-[10px] leading-4 font-semibold text-surface">{unread > 99 ? "99+" : unread}</span> : null}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} className="z-50 w-96 rounded-lg border border-rule bg-surface shadow-card">
          <div className="flex items-center justify-between border-b border-rule px-4 py-2">
            <p className="text-sm font-semibold">Notifications</p>
            <button type="button" className="text-xs text-brand hover:underline disabled:opacity-50" disabled={!unread || markAll.isPending} onClick={() => markAll.mutate()}>
              Mark all read
            </button>
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {(query.data?.items ?? []).length === 0 ? <li className="px-4 py-8 text-center text-sm text-muted">Nothing yet.</li> : null}
            {(query.data?.items ?? []).map((n) => (
              <li key={n.id} className="border-b border-rule last:border-0">
                <Link href={n.link || "/app"} className="block px-4 py-3 hover:bg-surface-2">
                  <p className="flex items-start justify-between gap-2 text-sm">
                    <span className={n.read_at ? "" : "font-semibold"}>{n.title}</span>
                    {!n.read_at ? <span className="sr-only">Unread</span> : null}
                  </p>
                  {n.body ? <p className="mt-0.5 text-xs text-muted">{n.body}</p> : null}
                  <p className="mt-1 text-[11px] text-muted">{formatDateTime(n.created_at)}</p>
                </Link>
              </li>
            ))}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
