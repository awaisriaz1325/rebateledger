import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import { headers } from "next/headers";
import { Providers } from "@/components/providers";
import { PRODUCT_NAME, SITE_URL } from "@/lib/site";
import "sonner/dist/styles.css"; // toast styles as a normal stylesheet (CSP blocks sonner's runtime <style> injection)
import "./globals.css";

const sans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-plex-sans", display: "swap" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono", display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: `${PRODUCT_NAME} — supplier rebate reconciliation`, template: `%s · ${PRODUCT_NAME}` },
  description: "Know which supplier rebates you earned, what you received and what is still missing.",
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // Reading headers makes every page render per request so the CSP nonce applies (ADR 0011).
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" suppressHydrationWarning className={`${sans.variable} ${mono.variable}`}>
      <body>
        <Providers nonce={nonce}>{children}</Providers>
      </body>
    </html>
  );
}
