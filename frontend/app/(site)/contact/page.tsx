import type { Metadata } from "next";
import Link from "next/link";
import { PageIntro, Placeholder, Section } from "@/components/site/site-chrome";

export const metadata: Metadata = { title: "Contact", description: "Talk to us about a pilot, security or billing.", alternates: { canonical: "/contact" } };

export default function Contact() {
  return (
    <>
      <PageIntro eyebrow="Contact" title="Talk to us">
        The fastest way to see whether we can help is a short pilot on your own data.
      </PageIntro>
      <Section>
        <div className="grid gap-6 sm:grid-cols-2">
          <div className="rounded-lg border border-rule bg-surface p-6">
            <h2 className="text-lg font-semibold">Start a pilot</h2>
            <p className="mt-2 text-sm text-muted">Tell us about your suppliers and systems; we reply within two business days.</p>
            <Link href="/request-a-pilot" className="mt-4 inline-flex h-10 items-center rounded-md bg-brand px-5 font-medium text-on-brand">Request a pilot</Link>
          </div>
          <div className="rounded-lg border border-rule bg-surface p-6">
            <h2 className="text-lg font-semibold">Everything else</h2>
            <Placeholder>Support, security and billing email addresses go here once the mailboxes exist.</Placeholder>
          </div>
        </div>
      </Section>
    </>
  );
}
