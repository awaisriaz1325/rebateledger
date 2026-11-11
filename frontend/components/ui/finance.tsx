/** Money, numbers and status badges for every status in the product (SPEC §10). */
import { AlertTriangle, CheckCircle2, CircleDashed, Clock, HelpCircle, MinusCircle, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { formatDate, formatMoney, formatQuantity, formatRatePercent, isNegative } from "@/lib/format";

/** Right-aligned, tabular, minus sign + colour for negatives (never colour alone). */
export function Money({ value, className, emphasize = false }: { value: string | null | undefined; className?: string; emphasize?: boolean }) {
  const negative = isNegative(value);
  return (
    <span className={cn("num", negative && "text-negative", emphasize && "font-semibold", className)} data-negative={negative || undefined}>
      {formatMoney(value)}
    </span>
  );
}

export function Qty({ value }: { value: string | null | undefined }) {
  return <span className="num">{formatQuantity(value)}</span>;
}

export function Rate({ value }: { value: string | null | undefined }) {
  return <span className="num">{formatRatePercent(value)}</span>;
}

export function DateText({ value }: { value: string | null | undefined }) {
  return <time dateTime={value ?? undefined}>{formatDate(value)}</time>;
}

type Tone = "positive" | "negative" | "warning" | "info" | "neutral" | "brand";

const TONES: Record<Tone, string> = {
  positive: "bg-positive-soft text-positive",
  negative: "bg-negative-soft text-negative",
  warning: "bg-warning-soft text-warning",
  info: "bg-info-soft text-info",
  neutral: "bg-surface-2 text-muted",
  brand: "bg-brand-soft text-brand",
};

const ICONS: Record<Tone, ReactNode> = {
  positive: <CheckCircle2 size={13} aria-hidden="true" />,
  negative: <XCircle size={13} aria-hidden="true" />,
  warning: <Clock size={13} aria-hidden="true" />,
  info: <HelpCircle size={13} aria-hidden="true" />,
  neutral: <CircleDashed size={13} aria-hidden="true" />,
  brand: <MinusCircle size={13} aria-hidden="true" />,
};

const STATUS: Record<string, { label: string; tone: Tone }> = {
  // reconciliation
  MATCHED: { label: "Matched", tone: "positive" },
  NOT_EARNED: { label: "Not earned", tone: "neutral" },
  PENDING: { label: "Pending", tone: "warning" },
  SHORT_PAID: { label: "Short-paid", tone: "negative" },
  MISSING: { label: "Missing", tone: "negative" },
  OVERPAID: { label: "Overpaid", tone: "warning" },
  NEEDS_REVIEW: { label: "Needs review", tone: "info" },
  // engine
  OK: { label: "OK", tone: "positive" },
  PARTIAL_PERIOD: { label: "Partial period", tone: "neutral" },
  BELOW_MINIMUM: { label: "Below minimum", tone: "neutral" },
  CAPPED: { label: "Capped", tone: "brand" },
  // agreement versions
  draft: { label: "Draft", tone: "neutral" },
  pending_approval: { label: "Awaiting approval", tone: "warning" },
  active: { label: "Active", tone: "positive" },
  superseded: { label: "Superseded", tone: "neutral" },
  archived: { label: "Archived", tone: "neutral" },
  inactive: { label: "Inactive", tone: "neutral" },
  // imports
  uploaded: { label: "Uploaded", tone: "neutral" },
  validating: { label: "Validating", tone: "info" },
  validated: { label: "Validated", tone: "info" },
  committing: { label: "Committing", tone: "info" },
  committed: { label: "Committed", tone: "positive" },
  failed: { label: "Failed", tone: "negative" },
  voided: { label: "Voided", tone: "neutral" },
  // runs / jobs
  queued: { label: "Queued", tone: "neutral" },
  running: { label: "Running", tone: "info" },
  succeeded: { label: "Succeeded", tone: "positive" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  dead: { label: "Failed", tone: "negative" },
  // claims
  ready: { label: "Ready", tone: "info" },
  submitted: { label: "Submitted", tone: "info" },
  acknowledged: { label: "Acknowledged", tone: "info" },
  resolved_recovered: { label: "Recovered", tone: "positive" },
  resolved_partial: { label: "Partly recovered", tone: "warning" },
  rejected: { label: "Rejected", tone: "negative" },
  written_off: { label: "Written off", tone: "neutral" },
  // approvals / subscriptions / invoices
  pending: { label: "Pending", tone: "warning" },
  approved: { label: "Approved", tone: "positive" },
  pilot: { label: "Pilot", tone: "brand" },
  past_due: { label: "Past due", tone: "warning" },
  suspended: { label: "Suspended", tone: "negative" },
  issued: { label: "Issued", tone: "info" },
  paid: { label: "Paid", tone: "positive" },
  void: { label: "Void", tone: "neutral" },
  deactivated: { label: "Deactivated", tone: "neutral" },
  STALE: { label: "Stale", tone: "warning" },
};

export function statusLabel(status: string): string {
  return STATUS[status]?.label ?? status.replaceAll("_", " ").toLowerCase();
}

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const s = STATUS[status] ?? { label: statusLabel(status), tone: "neutral" as Tone };
  return (
    <span className={cn("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium whitespace-nowrap", TONES[s.tone], className)}>
      {ICONS[s.tone]}
      {s.label}
    </span>
  );
}

export function Estimate() {
  return (
    <span className="inline-flex items-center gap-1 rounded bg-warning-soft px-1.5 py-0.5 text-xs font-medium text-warning">
      <AlertTriangle size={12} aria-hidden="true" />
      Estimate
    </span>
  );
}
