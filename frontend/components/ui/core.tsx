/** Core UI primitives (design tokens in app/globals.css; brief in docs/design-brief.md). */
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand text-on-brand hover:bg-brand-hover border border-transparent",
  secondary: "bg-surface text-ink border border-border-strong hover:bg-surface-2",
  ghost: "bg-transparent text-ink border border-transparent hover:bg-surface-2",
  danger: "bg-negative text-surface border border-transparent hover:opacity-90",
};
const SIZES: Record<Size, string> = { sm: "h-8 px-3 text-[13px]", md: "h-9 px-4 text-sm" };

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
});

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span role="status" aria-label={label} className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
  );
}

const control =
  "w-full rounded-md border border-border-strong bg-surface px-3 text-sm text-ink placeholder:text-muted disabled:opacity-60 aria-[invalid=true]:border-negative";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cn(control, "h-9", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cn(control, "min-h-20 py-2", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} className={cn(control, "h-9 pr-8", className)} {...rest}>
      {children}
    </select>
  );
});

export interface FieldProps {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}

/** Label + control + hint + error, wired with aria-describedby. Children must use the same id. */
export function Field({ id, label, error, hint, required, children, className }: FieldProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={id} className="text-[13px] font-medium text-ink">
        {label}
        {required ? <span className="text-muted"> (required)</span> : null}
      </label>
      {children}
      {hint && !error ? (
        <p id={`${id}-hint`} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-xs font-medium text-negative">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function describedBy(id: string, error?: string, hint?: string): string | undefined {
  return error ? `${id}-error` : hint ? `${id}-hint` : undefined;
}

export function Checkbox({ id, label, ...rest }: InputHTMLAttributes<HTMLInputElement> & { id: string; label: ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <input id={id} type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--brand)]" {...rest} />
      <label htmlFor={id} className="text-sm">
        {label}
      </label>
    </div>
  );
}

export function Card({ children, className, title, actions }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode }) {
  return (
    <section className={cn("rounded-lg border border-rule bg-surface", className)}>
      {title || actions ? (
        <header className="flex items-center justify-between gap-3 border-b border-rule px-4 py-3">
          {title ? <h2 className="text-sm font-semibold">{title}</h2> : <span />}
          {actions}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions, children }: { title: string; description?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="mt-1 max-w-3xl text-muted">{description}</p> : null}
        {children}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded border border-rule bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">{children}</kbd>;
}

export function Notice({ tone = "info", title, children, action }: { tone?: "info" | "warning" | "negative" | "positive"; title?: ReactNode; children?: ReactNode; action?: ReactNode }) {
  const tones = {
    info: "border-info/30 bg-info-soft",
    warning: "border-warning/30 bg-warning-soft",
    negative: "border-negative/30 bg-negative-soft",
    positive: "border-positive/30 bg-positive-soft",
  };
  return (
    <div role={tone === "negative" ? "alert" : "status"} className={cn("flex flex-wrap items-start justify-between gap-3 rounded-md border px-4 py-3", tones[tone])}>
      <div className="min-w-0">
        {title ? <p className="font-semibold">{title}</p> : null}
        {children ? <div className="text-sm">{children}</div> : null}
      </div>
      {action}
    </div>
  );
}
