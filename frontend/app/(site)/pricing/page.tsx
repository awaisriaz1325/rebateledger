import type { Metadata } from "next";
import Link from "next/link";
import { CtaBand, PageIntro, Section } from "@/components/site/site-chrome";
import { formatMoney } from "@/lib/format";
import type { components } from "@/generated/api";

export const metadata: Metadata = { title: "Pricing", description: "Simple monthly plans for independent distributors. Start with a pilot on your own data.", alternates: { canonical: "/pricing" } };

type Plan = components["schemas"]["PublicPlan"];

async function plans(): Promise<Plan[] | null> {
  try {
    const res = await fetch(`${process.env.RL_API_ORIGIN ?? "http://127.0.0.1:8000"}/api/v1/public/plans`, { cache: "no-store" });
    return res.ok ? ((await res.json()) as Plan[]) : null;
  } catch {
    return null;
  }
}

function limit(n: number | null | undefined, unit: string): string {
  return n == null ? `Unlimited ${unit}` : `Up to ${n.toLocaleString("en-US")} ${unit}`;
}

export default async function Pricing() {
  const list = await plans();
  const paid = (list ?? []).filter((p) => p.code !== "pilot");
  return (
    <>
      <PageIntro eyebrow="Pricing" title="Simple monthly plans, invoiced">
        Every customer starts with a pilot on their own data. Plans are invoiced monthly; there is no card checkout.
      </PageIntro>
      <Section>
        {list === null ? (
          <p className="text-muted">Prices could not be loaded right now. <Link className="text-brand underline" href="/contact">Contact us</Link> for current pricing.</p>
        ) : (
          <div className="grid gap-6 md:grid-cols-3">
            {paid.map((p) => (
              <div key={p.code} className="flex flex-col rounded-lg border border-rule bg-surface p-6">
                <h2 className="text-lg font-semibold">{p.name}</h2>
                <p className="mt-2"><span className="text-3xl font-semibold">{formatMoney(p.monthly_price).replace(/\.00$/, "")}</span><span className="text-muted"> / month</span></p>
                <ul className="mt-4 flex flex-1 flex-col gap-1.5 text-sm text-muted">
                  <li>{limit(p.max_active_agreements, "active agreements")}</li>
                  <li>{limit(p.max_users, "users")}</li>
                  <li>{limit(p.max_import_rows_per_month, "imported rows a month")}</li>
                  <li>All features, reports and exports</li>
                </ul>
                <Link href={`/request-a-pilot?plan=${p.code}`} className="mt-6 inline-flex h-10 items-center justify-center rounded-md bg-brand font-medium text-on-brand">Request a pilot</Link>
              </div>
            ))}
          </div>
        )}
        <p className="mt-6 text-sm text-muted">Prices in USD, excluding any applicable taxes. [PLACEHOLDER: prices are proposals pending confirmation.]</p>
      </Section>
      <CtaBand />
    </>
  );
}
