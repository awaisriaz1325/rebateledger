import type { Metadata } from "next";
import { Suspense } from "react";
import { PilotForm } from "@/components/site/pilot-form";
import { PageIntro, Section } from "@/components/site/site-chrome";

export const metadata: Metadata = { title: "Request a pilot", description: "Try it on your own purchase data and rebate agreements.", alternates: { canonical: "/request-a-pilot" } };

export default function RequestAPilot() {
  return (
    <>
      <PageIntro eyebrow="Request a pilot" title="See your own rebates reconciled">
        A pilot uses a few months of purchase exports, your credit memos and two or three of your rebate agreements. We reply within two business days.
      </PageIntro>
      <Section>
        <Suspense>
          <PilotForm />
        </Suspense>
      </Section>
    </>
  );
}
