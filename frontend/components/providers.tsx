"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setNonce } from "get-nonce";
import { ThemeProvider } from "next-themes";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { ApiError } from "@/lib/api";

export function Providers({ children, nonce }: { children: ReactNode; nonce?: string }) {
  // Radix dialogs lock scrolling with an injected <style>; give it the per-request CSP nonce (idempotent).
  if (nonce) setNonce(nonce);
  const router = useRouter();
  const onAuthError = (error: unknown): void => {
    if (error instanceof ApiError && error.status === 401 && typeof window !== "undefined") {
      const here = window.location.pathname;
      if (here.startsWith("/app") || here.startsWith("/ops")) router.push(`/login?next=${encodeURIComponent(here)}`);
    }
  };
  const [client] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({ onError: onAuthError }),
        mutationCache: new MutationCache({ onError: onAuthError }),
        defaultOptions: {
          queries: {
            retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
            refetchOnWindowFocus: false,
          },
          mutations: { retry: false },
        },
      }),
  );
  return (
    <ThemeProvider attribute="data-theme" defaultTheme="system" enableSystem nonce={nonce} disableTransitionOnChange>
      <QueryClientProvider client={client}>
        {children}
        <Toaster position="bottom-right" closeButton richColors={false} />
      </QueryClientProvider>
    </ThemeProvider>
  );
}
