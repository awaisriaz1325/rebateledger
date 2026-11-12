import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PageIntro } from "@/components/site/site-chrome";
import { blogPosts } from "@/lib/blog";

export const metadata: Metadata = { title: "Blog", alternates: { canonical: "/blog" } };

/** Hidden (404) until the first post exists (SPEC §4.16). */
export default function Blog() {
  if (blogPosts().length === 0) notFound();
  return <PageIntro eyebrow="Blog" title="Notes on supplier rebates" />;
}
