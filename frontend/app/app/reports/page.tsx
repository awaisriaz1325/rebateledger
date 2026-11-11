import { PageHeader } from "@/components/ui/core";
import { EmptyState } from "@/components/ui/states";

export default function ReportsPage() {
  return (
    <>
      <PageHeader title="Reports" description="Exports and evidence packs for your finance team and suppliers." />
      <EmptyState title="Reports are coming next">Until then, every table has a CSV export button, and each result has an Explain view you can share.</EmptyState>
    </>
  );
}
