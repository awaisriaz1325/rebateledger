/** Loading, empty, error, permission-denied and stale states (SPEC §10: no blank screens). */
import type { ReactNode } from "react";
import { ApiError, errorMessage } from "@/lib/api";
import { Button, Notice } from "@/components/ui/core";

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div aria-hidden="true" className={`skeleton ${className}`} />;
}

export function TableSkeleton({ rows = 6, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-2 py-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-rule px-6 py-12 text-center">
      <p className="text-base font-semibold">{title}</p>
      {children ? <div className="max-w-md text-sm text-muted">{children}</div> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

export function PermissionDenied({ children }: { children?: ReactNode }) {
  return (
    <Notice tone="warning" title="You don't have access to this">
      {children ?? "Your role in this organization does not include this area. Ask an Owner or Admin if you need access."}
    </Notice>
  );
}

/** Inline error with retry; permission errors render the permission-denied explanation. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (error instanceof ApiError && (error.code === "FORBIDDEN" || error.status === 403)) {
    return <PermissionDenied>{error.problem.detail}</PermissionDenied>;
  }
  const requestId = error instanceof ApiError ? error.problem.request_id : undefined;
  return (
    <Notice
      tone="negative"
      title="This could not be loaded"
      action={onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : undefined}
    >
      <p>{errorMessage(error)}</p>
      {requestId ? <p className="mt-1 font-mono text-xs text-muted">Request id {requestId}</p> : null}
    </Notice>
  );
}

/** Wraps the four states of a query. */
export function QueryState<T>({
  query,
  empty,
  isEmpty,
  loading,
  children,
}: {
  query: { isPending: boolean; isError: boolean; error: unknown; data: T | undefined; refetch: () => unknown };
  empty?: ReactNode;
  isEmpty?: (data: T) => boolean;
  loading?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <>{loading ?? <TableSkeleton />}</>;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const data = query.data as T;
  if (empty && isEmpty?.(data)) return <>{empty}</>;
  return <>{children(data)}</>;
}

export function StaleBanner({ reason, action }: { reason?: string | null; action?: ReactNode }) {
  return (
    <Notice tone="warning" title="Inputs changed since the last run" action={action}>
      {reason ? `Reason: ${reason}. ` : ""}Results shown are from the last run. Re-run to update them.
    </Notice>
  );
}
