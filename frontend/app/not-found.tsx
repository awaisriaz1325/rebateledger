import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-[70vh] max-w-xl flex-col justify-center gap-4 px-6">
      <p className="text-sm font-medium text-brand">404</p>
      <h1 className="text-3xl font-semibold">We can&rsquo;t find that page</h1>
      <p className="text-muted">The link may be old or mistyped.</p>
      <div className="flex gap-4"><Link href="/" className="text-brand underline">Home</Link><Link href="/app" className="text-brand underline">Your dashboard</Link></div>
    </main>
  );
}
