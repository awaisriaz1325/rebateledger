"use client";

import { SettingsForm } from "@/components/settings-form";
import { useStepUp } from "@/components/step-up";
import { Button, Card } from "@/components/ui/core";
import { api, idempotencyKey, unwrap } from "@/lib/api";
import { useExporter } from "@/lib/exports";
import { can, useSession } from "@/lib/session";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const ZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu", "America/Puerto_Rico"];

export default function OrganizationSettings() {
  const session = useSession();
  return (
    <>
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
      {can(session, "full_export") ? <FullExport /> : null}
    </>
  );
}

function FullExport() {
  const stepUp = useStepUp();
  const exporter = useExporter();
  return (
    <div className="mt-6">
      <Card title="Your data">
        <p className="text-sm text-muted">
          Download everything in your organization: one CSV per table, the original files you imported, and all attachments. It is prepared in the background; the download stays available for 24 hours.
        </p>
        <Button
          className="mt-4"
          variant="secondary"
          loading={exporter.busy !== null}
          onClick={() => void exporter.run("full", () => stepUp(async () => unwrap(await api.POST("/api/v1/org/data-export", { headers: { "Idempotency-Key": idempotencyKey() } }))))}
        >
          Export all data
        </Button>
      </Card>
    </div>
  );
}
