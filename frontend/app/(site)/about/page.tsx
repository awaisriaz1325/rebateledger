import type { Metadata } from "next";
import { PageIntro, Placeholder, Section } from "@/components/site/site-chrome";
import { PRODUCT_NAME } from "@/lib/site";

export const metadata: Metadata = { title: "About", description: `Why ${PRODUCT_NAME} exists and how we build it.`, alternates: { canonical: "/about" } };

export default function About() {
  return (
    <>
      <PageIntro eyebrow="About" title="Rebates are part of your margin. They deserve real accounting.">
        Independent distributors earn supplier rebates on volume, growth and product mix, then track them in spreadsheets and hope the credits arrive. {PRODUCT_NAME} exists to make that work exact, explainable and fast.
      </PageIntro>
      <Section title="How we build">
        <ul className="grid gap-4 text-sm sm:grid-cols-3">
          <li className="rounded-lg border border-rule bg-surface p-5"><strong>Correct before fast.</strong> Money is exact decimal arithmetic everywhere, and every amount can be explained step by step.</li>
          <li className="rounded-lg border border-rule bg-surface p-5"><strong>Overlay, not replacement.</strong> We work from your exports; we never ask you to change your ERP.</li>
          <li className="rounded-lg border border-rule bg-surface p-5"><strong>No guessing.</strong> When a rule or a date is ambiguous we ask a person rather than pick an answer.</li>
        </ul>
      </Section>
      <Section title="Team">
        <Placeholder>Founder and team bios go here.</Placeholder>
      </Section>
    </>
  );
}
