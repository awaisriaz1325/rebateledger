import type { Metadata } from "next";
import { LegalNotice, PageIntro } from "@/components/site/site-chrome";

export const metadata: Metadata = { title: "Privacy Policy", description: "How we collect, use and protect personal data.", alternates: { canonical: "/privacy" }, robots: { index: false } };

/** Template only: must not ship to production until reviewed (SPEC §4.16). */
export default function PrivacyPage() {
  return (
    <>
      <PageIntro eyebrow="Legal" title="Privacy Policy" />
      <LegalNotice />
      <article className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
        <p className="text-sm text-muted">Last updated: [PLACEHOLDER: date]</p>
        <section className="mt-8"><h2 className="text-xl font-semibold">Who we are</h2><p className="mt-2 text-muted">[PLACEHOLDER: legal entity name, address, contact for privacy questions.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">What we collect</h2><p className="mt-2 text-muted">Account data (name, work email, role), security data (sign-in times, IP address, browser, two-factor status), and the business data your organization uploads (purchase lines, supplier credits, agreements, claims). Website visitors who request a pilot provide name, work email, company and the details they choose to share.</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Why we use it</h2><p className="mt-2 text-muted">To provide the service your organization contracted for, keep accounts secure, send transactional and security emails, invoice your organization, and reply to pilot requests. We do not sell personal data and do not use customer business data to train AI models; the service has no AI features.</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Processors</h2><p className="mt-2 text-muted">[PLACEHOLDER: hosting, email delivery and other sub-processors with locations — see the Data Processing Addendum.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Retention</h2><p className="mt-2 text-muted">Business data is kept for the life of your organization&rsquo;s account and deleted after the account is closed and the grace period ends. Audit records are kept for the life of the organization. [PLACEHOLDER: confirm periods.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Your rights</h2><p className="mt-2 text-muted">[PLACEHOLDER: rights under applicable US state laws (e.g. CCPA/CPRA) and how to exercise them.]</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Cookies</h2><p className="mt-2 text-muted">We use one strictly necessary session cookie when you sign in. See the Cookie notice.</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Changes</h2><p className="mt-2 text-muted">We will post changes here and notify account owners of material changes.</p></section>
      </article>
    </>
  );
}
