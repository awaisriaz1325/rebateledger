import Link from "next/link";
import type { ReactNode } from "react";
import { PRODUCT_NAME } from "@/lib/site";

const NAV = [
  ["/how-it-works", "How it works"],
  ["/features", "Features"],
  ["/security", "Security"],
  ["/pricing", "Pricing"],
  ["/about", "About"],
] as const;

export function SiteHeader({ showBlog }: { showBlog: boolean }) {
  return (
    <header className="border-b border-rule bg-surface">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <Link href="/" className="inline-flex items-center gap-2 font-semibold">
          <span aria-hidden="true" className="inline-block h-5 w-5 rounded-sm bg-brand" />
          {PRODUCT_NAME}
        </Link>
        <nav aria-label="Main" className="order-3 w-full sm:order-none sm:w-auto">
          <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
            {NAV.map(([href, label]) => <li key={href}><Link href={href} className="hover:text-brand">{label}</Link></li>)}
            {showBlog ? <li><Link href="/blog" className="hover:text-brand">Blog</Link></li> : null}
          </ul>
        </nav>
        <div className="flex items-center gap-3 text-sm">
          <Link href="/login" className="hover:text-brand">Sign in</Link>
          <Link href="/request-a-pilot" className="inline-flex h-9 items-center rounded-md bg-brand px-4 font-medium text-on-brand">Request a pilot</Link>
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-rule bg-surface">
      <div className="mx-auto grid max-w-6xl grid-cols-2 gap-8 px-4 py-10 text-sm sm:grid-cols-4 sm:px-6">
        <div className="col-span-2 sm:col-span-1">
          <p className="font-semibold">{PRODUCT_NAME}</p>
          <p className="mt-2 text-muted">Supplier rebate reconciliation for independent wholesale distributors.</p>
        </div>
        <FooterCol title="Product" links={[["/how-it-works", "How it works"], ["/features", "Features"], ["/pricing", "Pricing"], ["/security", "Security"]]} />
        <FooterCol title="Company" links={[["/about", "About"], ["/contact", "Contact"], ["/request-a-pilot", "Request a pilot"]]} />
        <FooterCol title="Legal" links={[["/privacy", "Privacy Policy"], ["/terms", "Terms of Service"], ["/dpa", "Data Processing Addendum"], ["/cookies", "Cookie notice"]]} />
      </div>
      <p className="mx-auto max-w-6xl px-4 pb-8 text-xs text-muted sm:px-6">© {new Date().getFullYear()} {PRODUCT_NAME}. [PLACEHOLDER: legal entity name and address].</p>
    </footer>
  );
}

function FooterCol({ title, links }: { title: string; links: readonly (readonly [string, string])[] }) {
  return (
    <div>
      <p className="font-medium">{title}</p>
      <ul className="mt-2 flex flex-col gap-1.5 text-muted">{links.map(([href, label]) => <li key={href}><Link href={href} className="hover:text-ink">{label}</Link></li>)}</ul>
    </div>
  );
}

/** A section with a consistent rhythm on marketing pages. */
export function Section({ children, title, intro, id }: { children?: ReactNode; title?: string; intro?: ReactNode; id?: string }) {
  return (
    <section id={id} className="mx-auto max-w-6xl px-4 py-12 sm:px-6">
      {title ? <h2 className="text-2xl font-semibold tracking-tight">{title}</h2> : null}
      {intro ? <p className="mt-2 max-w-3xl text-muted">{intro}</p> : null}
      {children ? <div className={title || intro ? "mt-8" : ""}>{children}</div> : null}
    </section>
  );
}

export function PageIntro({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl px-4 pt-16 pb-4 sm:px-6">
      {eyebrow ? <p className="text-sm font-medium text-brand">{eyebrow}</p> : null}
      <h1 className="mt-2 max-w-3xl text-4xl font-semibold tracking-tight">{title}</h1>
      {children ? <div className="mt-4 max-w-3xl text-lg text-muted">{children}</div> : null}
    </div>
  );
}

/** Visible marker for proof that does not exist yet (SPEC §4.16 content integrity). */
export function Placeholder({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border-2 border-dashed border-border-strong p-6 text-sm text-muted">[PLACEHOLDER] {children}</div>;
}

export function LegalNotice() {
  return (
    <div role="note" className="mx-auto mt-6 max-w-3xl rounded-md border border-warning/40 bg-warning-soft px-4 py-3 text-sm">
      <strong>[LEGAL REVIEW REQUIRED]</strong> This is a template, not legal advice. It must be reviewed by a qualified lawyer before it is used in production.
    </div>
  );
}

export function CtaBand() {
  return (
    <Section>
      <div className="rounded-xl bg-brand px-6 py-10 text-on-brand sm:px-10">
        <h2 className="text-2xl font-semibold">See it on your own data</h2>
        <p className="mt-2 max-w-2xl opacity-90">A pilot uses exports you already have: purchase history, credit memos and your rebate agreements. No ERP integration and no change to how you work.</p>
        <Link href="/request-a-pilot" className="mt-6 inline-flex h-10 items-center rounded-md bg-surface px-5 font-medium text-brand">Request a pilot</Link>
      </div>
    </Section>
  );
}
