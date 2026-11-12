import type { Metadata } from "next";
import Link from "next/link";
import { CtaBand, Placeholder, Section } from "@/components/site/site-chrome";
import { PRODUCT_NAME } from "@/lib/site";

export const metadata: Metadata = { alternates: { canonical: "/" } };

const PROBLEMS = [
  ["Rebates are earned in spreadsheets", "Volume tiers, growth targets and per-unit programs live in PDFs and workbooks that one person understands."],
  ["Credits arrive late, short or never", "Supplier credit memos rarely say which period or program they pay, so short payments go unnoticed."],
  ["Nobody can prove the number", "When a supplier disputes a claim, you need the calculation, the lines and the terms — not a gut feel."],
] as const;

const STEPS = [
  ["Import what you already export", "Purchase lines and supplier credits as CSV or Excel. Map the columns once and save the template."],
  ["Write each agreement as rules", "Tiers, growth, per-unit, caps and minimums in plain terms, versioned with effective dates."],
  ["Reconcile expected vs received", "Every period gets an expected amount you can explain line by line, matched against the credits received."],
  ["Recover what is missing", "Open a claim, send an evidence pack, link the credit when it arrives."],
] as const;

export default function Home() {
  return (
    <>
      <div className="mx-auto max-w-6xl px-4 pt-20 pb-8 sm:px-6">
        <p className="text-sm font-medium text-brand">For independent US wholesale distributors</p>
        <h1 className="mt-3 max-w-4xl text-4xl font-semibold tracking-tight sm:text-5xl">Know which supplier rebates you earned, received and are still owed.</h1>
        <p className="mt-5 max-w-2xl text-lg text-muted">
          {PRODUCT_NAME} turns your rebate agreements into precise rules, calculates what each supplier owes you from your own purchase data, and shows which credits are missing — with the working shown.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/request-a-pilot" className="inline-flex h-11 items-center rounded-md bg-brand px-6 font-medium text-on-brand">Request a pilot</Link>
          <Link href="/how-it-works" className="inline-flex h-11 items-center rounded-md border border-border-strong px-6 font-medium">See how it works</Link>
        </div>
        <p className="mt-4 text-sm text-muted">Works from the exports you already have. No ERP integration, no card required.</p>
      </div>

      <Section title="Why rebates slip through">
        <div className="grid gap-6 sm:grid-cols-3">
          {PROBLEMS.map(([title, body]) => (
            <div key={title} className="rounded-lg border border-rule bg-surface p-5">
              <h3 className="font-semibold">{title}</h3>
              <p className="mt-2 text-sm text-muted">{body}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section title="From exports to recovered money" intro="Four steps, all inside one workspace your finance team controls.">
        <ol className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map(([title, body], i) => (
            <li key={title} className="rounded-lg border border-rule bg-surface p-5">
              <span className="text-sm font-semibold text-brand">Step {i + 1}</span>
              <h3 className="mt-1 font-semibold">{title}</h3>
              <p className="mt-2 text-sm text-muted">{body}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Built for numbers you can defend">
        <ul className="grid gap-4 text-sm sm:grid-cols-2">
          <li className="rounded-lg border border-rule bg-surface p-5"><strong>Explain every amount.</strong> Each expected rebate shows the eligible lines, the tier reached, the formula with your numbers in it, and the rounding — so anyone can recompute it by hand.</li>
          <li className="rounded-lg border border-rule bg-surface p-5"><strong>Never guess.</strong> Ambiguous dates, missing baselines or overlapping terms are flagged for a person to decide, never silently assumed.</li>
          <li className="rounded-lg border border-rule bg-surface p-5"><strong>History that does not move.</strong> Agreement versions and calculation runs are immutable; changes create new versions and new runs you can compare.</li>
          <li className="rounded-lg border border-rule bg-surface p-5"><strong>Your data, isolated.</strong> Every organization is separated in the database itself, with two-factor sign-in and a tamper-evident audit log. <Link href="/security" className="text-brand underline">How we protect your data</Link></li>
        </ul>
      </Section>

      <Section title="What customers say">
        <Placeholder>Customer quotes and results will appear here once pilot customers agree to share them. We do not publish invented testimonials or statistics.</Placeholder>
      </Section>

      <CtaBand />
    </>
  );
}
