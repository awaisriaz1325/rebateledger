import type { Metadata } from "next";
import { CtaBand, PageIntro, Section } from "@/components/site/site-chrome";

export const metadata: Metadata = { title: "Features", description: "Agreement modelling, imports, deterministic calculation, reconciliation, claims, tier tracking and reports.", alternates: { canonical: "/features" } };

const GROUPS = [
  ["Agreements", ["Flat %, all-units and incremental tiers", "Growth over prior period or fixed baseline", "Per-unit amounts and fixed bonuses", "Caps, minimum payouts, rounding and payment terms", "Eligibility by category, SKU, branch or line flags", "Versioning with effective dates, four-eyes approval, side-by-side comparison", "Dry-run preview against imported data"]],
  ["Imports", ["CSV and Excel, up to 1,000,000 rows per file", "Saved column mappings per file type", "Explicit date and number formats", "200-row preview, full background validation, downloadable error report", "Unknown supplier codes resolved before commit", "Duplicate detection and void with audit trail"]],
  ["Reconciliation", ["Expected vs received per agreement period", "Automatic credit matching by reference, manual split allocation", "Tolerances you set, in amount and percent", "Stale-result detection when inputs change", "Run-to-run comparison"]],
  ["Claims", ["Claims from short-paid or missing periods", "Lifecycle from draft to recovered or written off", "Evidence packs: PDF and CSV appendix", "Recoveries recorded only from real credits", "Reminders for follow-ups and aging"]],
  ["Insight", ["Dashboard of open variance and recoveries", "Tier tracker with clearly labelled estimates", "Reports in CSV, Excel and PDF", "Full data export at any time"]],
  ["Control", ["Roles: owner, admin, analyst, viewer", "Two-factor sign-in and step-up for sensitive actions", "Tamper-evident audit log", "Support access only when you grant it"]],
] as const;

export default function Features() {
  return (
    <>
      <PageIntro eyebrow="Features" title="Everything a finance team needs to run supplier rebates" />
      <Section>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {GROUPS.map(([title, items]) => (
            <div key={title} className="rounded-lg border border-rule bg-surface p-6">
              <h2 className="text-lg font-semibold">{title}</h2>
              <ul className="mt-3 flex list-disc flex-col gap-1.5 pl-5 text-sm text-muted">{items.map((i) => <li key={i}>{i}</li>)}</ul>
            </div>
          ))}
        </div>
        <p className="mt-6 text-sm text-muted">Not included in this version: ERP integrations, supplier portals, card payments and AI features.</p>
      </Section>
      <CtaBand />
    </>
  );
}
