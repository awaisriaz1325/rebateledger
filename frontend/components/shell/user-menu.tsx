"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import { Menu } from "@/components/ui/overlay";
import { api, setCsrfToken } from "@/lib/api";
import type { SessionInfo } from "@/lib/session";

export function UserMenu({ session, onHelp }: { session: SessionInfo; onHelp: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const { theme, setTheme } = useTheme();
  const name = session.user?.name || session.user?.email || "Account";
  const initials = name.split(/[\s@.]+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("");
  return (
    <Menu
      trigger={
        <button type="button" className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">
          <span aria-hidden="true">{initials}</span>
          <span className="sr-only">Account menu for {name}</span>
        </button>
      }
      items={[
        { label: `Signed in as ${session.user?.email ?? ""}`, onSelect: () => router.push("/app/settings/profile") },
        { label: "Profile & security", onSelect: () => router.push("/app/settings/profile") },
        { label: `Theme: ${theme ?? "system"} (switch)`, onSelect: () => setTheme(theme === "light" ? "dark" : theme === "dark" ? "system" : "light") },
        { label: "Keyboard shortcuts", onSelect: onHelp },
        {
          label: "Sign out",
          danger: true,
          onSelect: async () => {
            await api.POST("/api/v1/auth/logout");
            setCsrfToken(null);
            qc.clear();
            router.push("/login");
          },
        },
      ]}
    />
  );
}
