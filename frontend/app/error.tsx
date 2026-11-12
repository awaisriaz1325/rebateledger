"use client";

import Link from "next/link";

/** 500 page. Shows a reference id only (never stack traces or messages). */
export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main id="main" className="mx-auto flex min-h-[70vh] max-w-xl flex-col justify-center gap-4 px-6">
      <p className="text-sm font-medium text-negative">Something went wrong</p>
      <h1 className="text-3xl font-semibold">This page could not be loaded</h1>
      <p className="text-muted">Nothing you entered was lost on our side. Try again, and if it keeps happening contact support{error.digest ? <> with reference <code className="font-mono">{error.digest}</code></> : null}.</p>
      <div className="flex gap-4"><button type="button" onClick={reset} className="text-brand underline">Try again</button><Link href="/" className="text-brand underline">Home</Link></div>
    </main>
  );
}
