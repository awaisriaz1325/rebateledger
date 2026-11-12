import type { MetadataRoute } from "next";
import { blogPosts } from "@/lib/blog";
import { SITE_URL } from "@/lib/site";

const PAGES = ["", "/how-it-works", "/features", "/security", "/pricing", "/about", "/contact", "/request-a-pilot"];

/** Public marketing pages only. Legal templates are excluded until reviewed. */
export default function sitemap(): MetadataRoute.Sitemap {
  return [...PAGES, ...(blogPosts().length ? ["/blog"] : [])].map((p) => ({ url: `${SITE_URL}${p}`, changeFrequency: "monthly", priority: p === "" ? 1 : 0.7 }));
}
