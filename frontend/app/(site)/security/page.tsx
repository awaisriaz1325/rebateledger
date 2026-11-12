import type { Metadata } from "next";
import { PageIntro, Section } from "@/components/site/site-chrome";

export const metadata: Metadata = { title: "Security", description: "How we protect your purchase and rebate data: tenant isolation, encryption, two-factor sign-in and auditability.", alternates: { canonical: "/security" } };

const ITEMS = [
  ["Isolation in the database", "Every table with customer data carries your organization's id, and PostgreSQL row-level security enforces the boundary in addition to application checks. Automated tests try to read and change other organizations' data on every endpoint."],
  ["Sign-in", "Passwords are hashed with Argon2id. Owners and admins must use two-factor authentication; any organization can require it for everyone. Sensitive actions ask you to confirm your password again."],
  ["Encryption", "In production the service is HTTPS-only (TLS with HSTS), and the database and file storage use the hosting provider's encryption at rest. Two-factor secrets are additionally encrypted by the application."],
  ["Least privilege", "Four roles with named permissions; every API endpoint declares the permission it needs and checks that the object belongs to your organization."],
  ["Audit trail", "Sign-ins, changes to agreements, imports, runs, claims, exports and settings are written to an append-only, hash-chained audit log you can export."],
  ["Support access on your terms", "Our team cannot see your business data unless an owner or admin grants time-limited access. You see a banner while it is active, can revoke it at any time, and every action is logged in your audit log."],
  ["Safe exports", "Spreadsheet exports neutralise formula injection. PDF generation cannot make network requests. Download links expire after 15 minutes."],
  ["Your data stays yours", "Export everything at any time as CSV plus your original files. Data is never deleted because of a late payment."],
] as const;

export default function SecurityPage() {
  return (
    <>
      <PageIntro eyebrow="Security" title="Built for finance data from the first line of code">
        We describe only controls that exist today. We do not claim certifications we do not hold.
      </PageIntro>
      <Section>
        <div className="grid gap-6 sm:grid-cols-2">
          {ITEMS.map(([title, body]) => (
            <div key={title} className="rounded-lg border border-rule bg-surface p-6">
              <h2 className="text-lg font-semibold">{title}</h2>
              <p className="mt-2 text-sm text-muted">{body}</p>
            </div>
          ))}
        </div>
        <p className="mt-8 text-sm text-muted">Certifications: none yet. [PLACEHOLDER: list SOC 2 or similar only once an audit has actually been completed.] Questions about security? <a className="text-brand underline" href="/contact">Contact us</a>.</p>
      </Section>
    </>
  );
}
