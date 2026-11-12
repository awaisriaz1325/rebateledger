import type { Metadata } from "next";
import { LegalNotice, PageIntro } from "@/components/site/site-chrome";

export const metadata: Metadata = { title: "Cookie notice", description: "Which cookies we use and why.", alternates: { canonical: "/cookies" }, robots: { index: false } };

/** Template only: must not ship to production until reviewed (SPEC §4.16). */
export default function CookiesPage() {
  return (
    <>
      <PageIntro eyebrow="Legal" title="Cookie notice" />
      <LegalNotice />
      <article className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
        <p className="text-sm text-muted">Last updated: [PLACEHOLDER: date]</p>
        <section className="mt-8"><h2 className="text-xl font-semibold">Strictly necessary</h2><p className="mt-2 text-muted">When you sign in we set one cookie, __Host-rl_session, to keep you signed in securely. It is HTTP-only, secure and same-site, and it expires when your session ends or after the absolute session limit.</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">Analytics</h2><p className="mt-2 text-muted">The marketing website may use privacy-friendly, cookieless analytics. The app itself has no analytics or third-party scripts.</p></section>
        <section className="mt-8"><h2 className="text-xl font-semibold">No other cookies</h2><p className="mt-2 text-muted">We do not use advertising or tracking cookies. If that ever changes, we will ask for consent first, with an equally easy option to reject.</p></section>
      </article>
    </>
  );
}
