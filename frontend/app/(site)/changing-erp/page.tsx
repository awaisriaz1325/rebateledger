import type { Metadata } from "next";
import { PageIntro, Section } from "@/components/site/site-chrome";

export const metadata: Metadata = {
  title: "Changing ERP?",
  description: "Keep your supplier rebate history and claims through an ERP migration. RebateLedger works from exported files, so it does not depend on the system you leave or the one you move to.",
  alternates: { canonical: "/changing-erp" },
};

const POINTS = [
  ["Your rebate history lives outside the ERP", "Agreements, imported purchase lines, supplier credits, calculation runs and claims are stored in RebateLedger. Retiring the old system does not take your rebate records with it."],
  ["Old and new systems side by side", "Imports are files (CSV or XLSX), not a live connection. Load history exported from the old ERP and new months from the new one; supplier aliases map the different supplier codes to one supplier."],
  ["Past results stay reproducible", "Every calculation run records its inputs and engine version, so last year's numbers can be regenerated exactly, even after the system that produced the data is gone."],
  ["Mappings for common distribution ERPs", "Import presets exist for Epicor Prophet 21, Epicor Eclipse, Infor CloudSuite Distribution (SX.e), NetSuite, Acumatica and QuickBooks. They are being checked against real customer reports; until then each one is labelled unverified and you confirm the mapping."],
  ["Export everything, any time", "Download all of your data as CSV plus your original files, whether you are migrating to us, through us or away from us."],
] as const;

export default function ChangingErpPage() {
  return (
    <>
      <PageIntro eyebrow="ERP migrations" title="Changing ERP? Keep your rebate history.">
        Many distributors are planning an ERP move. Rebate agreements, accruals and open claims are easy to lose in the switch. RebateLedger keeps them in one place that does not depend on either system.
      </PageIntro>
      <Section title="Why now">
        <p className="max-w-3xl text-muted">
          Epicor has announced final on-premises releases for Prophet 21, Kinetic and BisTrack. For Prophet 21, the final on-premises release is tentatively scheduled for May 2028, with active support through 30 June 2029 (
          <a className="text-brand underline" href="https://www.cio.com/article/4114170/epicor-sets-timeline-to-sunset-on-prem-erp-as-cloud-becomes-the-only-path-forward.html" rel="noopener noreferrer" target="_blank">
            CIO.com, 7 January 2026<span className="sr-only"> (opens in a new tab)</span>
          </a>
          , accessed 17 November 2026). Check the current dates with Epicor for your own plan.
        </p>
      </Section>
      <Section title="How RebateLedger helps during a migration">
        <div className="grid gap-6 sm:grid-cols-2">
          {POINTS.map(([title, body]) => (
            <div key={title} className="rounded-lg border border-rule bg-surface p-6">
              <h3 className="text-lg font-semibold">{title}</h3>
              <p className="mt-2 text-sm text-muted">{body}</p>
            </div>
          ))}
        </div>
        <p className="mt-8 text-sm text-muted">
          Planning a migration? <a className="text-brand underline" href="/request-a-pilot">Request a pilot</a> and start with your current exports.
        </p>
      </Section>
    </>
  );
}
