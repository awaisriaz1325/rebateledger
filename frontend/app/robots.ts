import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/app", "/ops", "/api", "/login", "/mfa", "/accept-invite", "/reset-password", "/verify-email", "/confirm-email-change", "/unsubscribe"] },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
