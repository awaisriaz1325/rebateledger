import Link from "next/link";
import { PRODUCT_NAME } from "@/lib/site";

/** Temporary home until the marketing site (Phase 9). No claims, no proof, no placeholders posing as facts. */
export default function Home() {
  return (
    <main id="main" className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-6 px-6">
      <p className="inline-flex items-center gap-2 text-sm font-semibold"><span aria-hidden="true" className="inline-block h-5 w-5 rounded-sm bg-brand" />{PRODUCT_NAME}</p>
      <h1 className="text-4xl font-semibold tracking-tight">Know which supplier rebates you earned, received and are still owed.</h1>
      <p className="text-lg text-muted">Rebate reconciliation for independent wholesale distributors, built from the exports you already have.</p>
      <div><Link href="/login" className="inline-flex h-10 items-center rounded-md bg-brand px-5 font-medium text-on-brand">Sign in</Link></div>
    </main>
  );
}
