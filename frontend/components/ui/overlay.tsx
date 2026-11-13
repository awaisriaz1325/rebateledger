"use client";

/** Dialogs, drawers, menus and tabs on Radix primitives (focus trapping, ESC, ARIA). */
import { X } from "lucide-react";
import { Dialog as D, DropdownMenu as M, Tabs as T } from "radix-ui";
import { useRef, useState, type ReactNode } from "react";
import { Button, Input } from "@/components/ui/core";
import { cn } from "@/lib/cn";

/**
 * Return focus to wherever it was when an overlay opened (WCAG 2.4.3).
 *
 * Our overlays are opened from code (shortcuts, row actions), not from a Radix `Trigger`, so
 * Radix has no trigger to refocus and focus would fall to <body>. Radix fires
 * `onOpenAutoFocus` before it moves focus, so `document.activeElement` is still the opener.
 */
export function useReturnFocus(): { onOpenAutoFocus: () => void; onCloseAutoFocus: (e: Event) => void } {
  const opener = useRef<HTMLElement | null>(null);
  return {
    onOpenAutoFocus: () => {
      const el = document.activeElement;
      opener.current = el instanceof HTMLElement && el !== document.body ? el : null;
    },
    onCloseAutoFocus: (e: Event) => {
      const el = opener.current;
      opener.current = null;
      if (el?.isConnected) {
        e.preventDefault();
        el.focus();
      }
    },
  };
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  wide = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const focus = useReturnFocus();
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <D.Content
          {...focus}
          className={cn(
            "fixed top-1/2 left-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-rule bg-surface p-6 shadow-card",
            wide ? "max-w-3xl" : "max-w-lg",
          )}
        >
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <D.Title className="text-lg font-semibold">{title}</D.Title>
              {description ? <D.Description className="mt-1 text-sm text-muted">{description}</D.Description> : <D.Description className="sr-only">{title}</D.Description>}
            </div>
            <D.Close asChild>
              <button type="button" aria-label="Close" className="rounded p-1 text-muted hover:bg-surface-2">
                <X size={18} aria-hidden="true" />
              </button>
            </D.Close>
          </div>
          {children}
          {footer ? <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div> : null}
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

/**
 * Confirmation for destructive actions. When `typeToConfirm` is set the user must
 * type that text (irreversible actions, frontend rules).
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  typeToConfirm,
  pending = false,
  tone = "danger",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  typeToConfirm?: string;
  pending?: boolean;
  tone?: "danger" | "primary";
}) {
  const [typed, setTyped] = useState("");
  const ok = !typeToConfirm || typed === typeToConfirm;
  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) setTyped("");
        onOpenChange(v);
      }}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant={tone} onClick={onConfirm} disabled={!ok} loading={pending}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {typeToConfirm ? (
        <div className="flex flex-col gap-1.5">
          <label htmlFor="confirm-text" className="text-[13px]">
            Type <strong className="font-mono">{typeToConfirm}</strong> to confirm
          </label>
          <Input id="confirm-text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        </div>
      ) : null}
    </Dialog>
  );
}

export function Drawer({ open, onOpenChange, title, description, children }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: ReactNode; children: ReactNode }) {
  const focus = useReturnFocus();
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <D.Content {...focus} className="fixed top-0 right-0 z-50 flex h-full w-full max-w-2xl flex-col border-l border-rule bg-surface shadow-card">
          <div className="flex items-start justify-between gap-4 border-b border-rule px-6 py-4">
            <div className="min-w-0">
              <D.Title className="text-lg font-semibold">{title}</D.Title>
              {description ? <D.Description className="mt-1 text-sm text-muted">{description}</D.Description> : <D.Description className="sr-only">{title}</D.Description>}
            </div>
            <D.Close asChild>
              <button type="button" aria-label="Close" className="rounded p-1 text-muted hover:bg-surface-2">
                <X size={18} aria-hidden="true" />
              </button>
            </D.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-4">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

export function Menu({ trigger, items, label }: { trigger: ReactNode; /** Only when the trigger has no visible text of its own. */ label?: string; items: { label: string; onSelect: () => void; danger?: boolean; disabled?: boolean }[] }) {
  return (
    <M.Root>
      <M.Trigger asChild aria-label={label}>
        {trigger}
      </M.Trigger>
      <M.Portal>
        <M.Content align="end" sideOffset={6} className="z-50 min-w-48 rounded-md border border-rule bg-surface p-1 shadow-card">
          {items.map((item) => (
            <M.Item
              key={item.label}
              disabled={item.disabled}
              onSelect={item.onSelect}
              className={cn(
                "cursor-pointer rounded px-3 py-2 text-sm outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface-2",
                item.danger && "text-negative",
              )}
            >
              {item.label}
            </M.Item>
          ))}
        </M.Content>
      </M.Portal>
    </M.Root>
  );
}

export function Tabs({ tabs, value, onValueChange, label }: { tabs: { value: string; label: string; content: ReactNode }[]; value?: string; onValueChange?: (v: string) => void; label: string }) {
  return (
    <T.Root value={value} onValueChange={onValueChange} defaultValue={value ? undefined : tabs[0]?.value}>
      <T.List aria-label={label} className="mb-4 flex gap-1 border-b border-rule">
        {tabs.map((t) => (
          <T.Trigger
            key={t.value}
            value={t.value}
            className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted data-[state=active]:border-brand data-[state=active]:text-ink"
          >
            {t.label}
          </T.Trigger>
        ))}
      </T.List>
      {tabs.map((t) => (
        <T.Content key={t.value} value={t.value}>
          {t.content}
        </T.Content>
      ))}
    </T.Root>
  );
}
