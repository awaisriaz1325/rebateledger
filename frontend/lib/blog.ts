/** Blog posts live in content/blog/*.mdx. None exist yet, so the Blog link stays hidden
 * (SPEC §4.16). An MDX renderer is added together with the first post. */
import { existsSync, readdirSync } from "node:fs";
import path from "node:path";

export function blogPosts(): string[] {
  const dir = path.join(process.cwd(), "content", "blog");
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => f.endsWith(".mdx"));
}
