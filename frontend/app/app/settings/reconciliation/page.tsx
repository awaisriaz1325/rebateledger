"use client";

import { SettingsForm } from "@/components/settings-form";

export default function ReconciliationSettings() {
  return (
    <SettingsForm
      section="reconciliation"
      title="Reconciliation"
      intro="Tolerance T = max(absolute tolerance, percentage tolerance × expected). Differences within T are matched. Changes apply to new runs."
      fields={[
        { name: "abs_tolerance", label: "Absolute tolerance (USD)", kind: "decimal", hint: "Default 1.00" },
        { name: "pct_tolerance", label: "Percentage tolerance (as a fraction)", kind: "decimal", hint: "0.005 means 0.5%" },
        { name: "default_payment_terms_days", label: "Default payment terms (days)", kind: "integer", hint: "Used as the starting value for new agreements" },
        { name: "data_freshness_days", label: "Warn when purchase data is older than (days)", kind: "integer" },
        { name: "tier_alert_pct", label: "Tier alert: within this fraction of the next tier", kind: "decimal", hint: "0.10 means within 10%" },
        { name: "tier_alert_days", label: "Tier alert: with at most this many days left", kind: "integer" },
      ]}
    />
  );
}
