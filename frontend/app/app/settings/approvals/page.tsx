"use client";

import { SettingsForm } from "@/components/settings-form";

export default function ApprovalSettings() {
  return (
    <SettingsForm
      section="approvals"
      title="Approvals (four-eyes)"
      intro="When on, a different Admin or Owner must approve. Nobody can approve their own request, even after a role change."
      fields={[
        { name: "four_eyes_activation", label: "Require approval to activate agreement versions", kind: "bool" },
        { name: "four_eyes_writeoff", label: "Require approval to write off claims", kind: "bool" },
      ]}
    />
  );
}
