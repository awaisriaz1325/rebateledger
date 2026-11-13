"use client";

import { SettingsForm } from "@/components/settings-form";

export default function AccountingSettings() {
  return (
    <SettingsForm
      section="accounting"
      title="Accounting"
      intro="Your own general-ledger account codes, used in the month-end accrual journal you download. RebateLedger never posts to your ledger."
      fields={[
        { name: "gl_receivable_account", label: "Rebate receivable account", kind: "text", hint: "For example 1250 Rebates receivable" },
        { name: "gl_offset_account", label: "Offset account (rebate income or cost of goods)", kind: "text", hint: "Book supplier credits to this account when they arrive." },
      ]}
    />
  );
}
