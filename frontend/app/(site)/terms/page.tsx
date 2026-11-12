import type { Metadata } from "next";
import { LegalNotice, PageIntro } from "@/components/site/site-chrome";

export const metadata: Metadata = { title: "Terms of Service", description: "The agreement between your organization and us for using the service.", alternates: { canonical: "/terms" }, robots: { index: false } };

/** Template only: must not ship to production until reviewed (SPEC §4.16). */
export default function TermsPage() {
  return (
    <>
      <PageIntro eyebrow="Legal" title="Terms of Service" />
      <LegalNotice />
      <article className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
        <p className="text-sm text-muted">Last updated: [PLACEHOLDER: date]</p>
        <section className="mt-8"><h2 className="text-xl font-semibold">The service</h2><p className="mt-2 text-muted">[PLACEHOLDER: description of the service, plans and pilot terms.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Accounts</h2><p className="mt-2 text-muted">Your organization is responsible for its users, roles and the accuracy of the data it uploads. Calculations depend on the agreement terms you enter; you remain responsible for reviewing results before relying on them.</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Fees and invoices</h2><p className="mt-2 text-muted">Fees follow your plan and are invoiced; there is no card checkout. [PLACEHOLDER: payment terms, late payment, suspension to read-only, taxes.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Your data</h2><p className="mt-2 text-muted">You own your data. You can export it at any time. We process it only to provide the service, as described in the Data Processing Addendum.</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Acceptable use</h2><p className="mt-2 text-muted">[PLACEHOLDER: prohibited uses.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Warranties and liability</h2><p className="mt-2 text-muted">[PLACEHOLDER: disclaimers and limitation of liability.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Term and termination</h2><p className="mt-2 text-muted">[PLACEHOLDER: term, termination, data export and deletion after termination.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Governing law</h2><p className="mt-2 text-muted">[PLACEHOLDER: governing law and venue.]</p></section>
      </article>
    </>
  );
}
