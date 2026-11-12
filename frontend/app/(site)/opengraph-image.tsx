import { ImageResponse } from "next/og";
import { PRODUCT_NAME } from "@/lib/site";

export const alt = `${PRODUCT_NAME} — supplier rebate reconciliation for distributors`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "center", padding: 80, background: "#f6f5f1", color: "#17201b" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 20, fontSize: 40, fontWeight: 600 }}>
          <div style={{ width: 44, height: 44, borderRadius: 8, background: "#1d5c45" }} />
          {PRODUCT_NAME}
        </div>
        <div style={{ marginTop: 48, fontSize: 64, fontWeight: 600, lineHeight: 1.15, maxWidth: 1000 }}>Know which supplier rebates you earned, received and are still owed.</div>
        <div style={{ marginTop: 32, fontSize: 30, color: "#5b6660" }}>For independent US wholesale distributors</div>
      </div>
    ),
    size,
  );
}
