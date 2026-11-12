import type { Metadata } from "next";
import { CtaBand, PageIntro, Section } from "@/components/site/site-chrome";

export const metadata: Metadata = { title: "How it works", description: "From ERP exports to recovered rebates: import, model agreements, reconcile, claim.", alternates: { canonical: "/how-it-works" } };

const STEPS = [
  ["1. Import purchases and credits", "Upload CSV or Excel exports of purchase invoice lines and supplier credit memos. You map the columns once; dates, decimal separators and negative styles are chosen explicitly. Ambiguous dates such as 03/04 are never guessed. Files are validated in full before anything is saved, and duplicates are skipped."],
  ["2. Turn each agreement into rules", "Enter each rebate program: flat percentage, all-units or incremental tiers, growth over a baseline, per-unit amounts, fixed bonuses, caps, minimums, eligibility by category, SKU or flags. A plain-English summary is generated from the rules so you can check them against the contract. Versions are effective-dated and locked once active."],
  ["3. Run the calculation", "A run calculates the expected rebate for every agreement period from a frozen snapshot of your data and terms. The engine is deterministic: the same inputs always give the same result, and each result carries a step-by-step explanation."],
  ["4. Reconcile against credits", "Credits are matched to agreement periods automatically when the memo says which program they pay, and you split or allocate the rest. Each period shows expected, received, variance and status: matched, short-paid, missing, overpaid, pending or needs review."],
  ["5. Claim and recover", "Open a claim from any short-paid or missing period, send the supplier an evidence pack (PDF with the calculation plus the line listing), track follow-ups, and record recovery only when the actual credit arrives."],
] as const;

export default function HowItWorks() {
  return (
    <>
      <PageIntro eyebrow="How it works" title="From the exports you already have to money you can recover">
        No ERP integration and no change to how your team works. Everything starts with files you can export today.
      </PageIntro>
      <Section>
        <ol className="flex flex-col gap-6">
          {STEPS.map(([title, body]) => (
            <li key={title} className="rounded-lg border border-rule bg-surface p-6">
              <h2 className="text-lg font-semibold">{title}</h2>
              <p className="mt-2 text-muted">{body}</p>
            </li>
          ))}
        </ol>
      </Section>
      <CtaBand />
    </>
  );
}
