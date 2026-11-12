import type { Metadata } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";
import { SiteFooter, SiteHeader } from "@/components/site/site-chrome";
import { blogPosts } from "@/lib/blog";
import { PRODUCT_NAME, SITE_URL } from "@/lib/site";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: `${PRODUCT_NAME} — supplier rebate reconciliation for distributors`, template: `%s · ${PRODUCT_NAME}` },
  description: "Know which supplier rebates you earned, which you received and which are still missing. Built for independent US wholesale distributors, from the exports you already have.",
  openGraph: { type: "website", siteName: PRODUCT_NAME },
  twitter: { card: "summary_large_image" },
};

/** Cookieless analytics, marketing pages only, off unless configured (provider is [OPEN], SPEC §4.16).
 * The CSP in proxy.ts allows this origin on marketing routes only. */
const ANALYTICS_SRC = process.env.NEXT_PUBLIC_ANALYTICS_SRC;
const ANALYTICS_DOMAIN = process.env.NEXT_PUBLIC_ANALYTICS_DOMAIN;

/** JSON-LD for the organization and the product. No ratings, reviews or offers we cannot back up. */
function JsonLd({ nonce }: { nonce?: string }) {
  const data = [
    { "@context": "https://schema.org", "@type": "Organization", name: PRODUCT_NAME, url: SITE_URL },
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      name: PRODUCT_NAME,
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web",
      url: SITE_URL,
      description: "Supplier rebate reconciliation for independent wholesale distributors.",
    },
  ];
  // JSON is serialised by us from constants; "<" is escaped so it can never close the tag.
  const json = JSON.stringify(data).replace(/</g, "\\u003c");
  return <script type="application/ld+json" nonce={nonce} dangerouslySetInnerHTML={{ __html: json }} />;
}

export default async function SiteLayout({ children }: { children: ReactNode }) {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <>
      <JsonLd nonce={nonce} />
      {ANALYTICS_SRC ? <script defer src={ANALYTICS_SRC} data-domain={ANALYTICS_DOMAIN} nonce={nonce} /> : null}
      <a href="#main" className="sr-only-focusable fixed top-2 left-2 z-50 rounded bg-brand px-3 py-2 text-on-brand">Skip to content</a>
      <SiteHeader showBlog={blogPosts().length > 0} />
      <main id="main">{children}</main>
      <SiteFooter />
    </>
  );
}
