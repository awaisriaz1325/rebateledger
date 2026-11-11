"use client";

import { SettingsForm } from "@/components/settings-form";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const ZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu", "America/Puerto_Rico"];

export default function OrganizationSettings() {
  return (
    <SettingsForm
      section="profile"
      title="Organization"
      intro="Currency is USD in this version and cannot be changed."
      fields={[
        { name: "name", label: "Organization name", kind: "text" },
        { name: "legal_name", label: "Legal name (optional)", kind: "text" },
        { name: "timezone", label: "Timezone", kind: "select", options: ZONES.map((z) => ({ value: z, label: z.replace("_", " ") })), hint: "Due dates and “today” are evaluated in this timezone." },
        { name: "fiscal_year_start_month", label: "Fiscal year starts in", kind: "select", options: MONTHS.map((m, i) => ({ value: String(i + 1), label: m })), hint: "Fiscal-aligned agreement periods use this month." },
      ]}
    />
  );
}
