import type { Metadata } from "next";
import { LegalNotice, PageIntro } from "@/components/site/site-chrome";

export const metadata: Metadata = { title: "Data Processing Addendum", description: "How we process personal data on your organization's behalf.", alternates: { canonical: "/dpa" }, robots: { index: false } };

/** Template only: must not ship to production until reviewed (SPEC §4.16). */
export default function DpaPage() {
  return (
    <>
      <PageIntro eyebrow="Legal" title="Data Processing Addendum" />
      <LegalNotice />
      <article className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
        <p className="text-sm text-muted">Last updated: [PLACEHOLDER: date]</p>
        <section className="mt-8"><h2 className="text-xl font-semibold">Roles</h2><p className="mt-2 text-muted">Your organization is the controller of the personal data in its account; we act as processor.</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Instructions</h2><p className="mt-2 text-muted">We process personal data only on your documented instructions: to provide, secure and support the service.</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Security measures</h2><p className="mt-2 text-muted">Tenant isolation enforced in the database, encryption in transit and at rest in production, two-factor authentication for privileged roles, least-privilege access, tamper-evident audit logs, and support access only when you grant it.</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Sub-processors</h2><p className="mt-2 text-muted">[PLACEHOLDER: list of sub-processors, locations and notification process for changes.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">International transfers</h2><p className="mt-2 text-muted">[PLACEHOLDER: transfer mechanisms, if any.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Breach notification</h2><p className="mt-2 text-muted">[PLACEHOLDER: notification timeline and content.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Deletion and return</h2><p className="mt-2 text-muted">You can export all data at any time. [PLACEHOLDER: deletion timeline after termination.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Audits</h2><p className="mt-2 text-muted">[PLACEHOLDER: audit and information rights.]</p></section>
      </article>
    </>
  );
}
