"use client";

import { DealModel } from "@/components/deal-model";
import { PageHeader } from "@/components/ui/core";
import { PermissionDenied } from "@/components/ui/states";
import { can, useSession } from "@/lib/session";

export default function DealModelPage() {
  const session = useSession();
  if (!can(session, "edit_agreements")) return <PermissionDenied />;
  return (
    <>
      <PageHeader title="Deal modelling" description="Before you sign, see what proposed terms would have paid on your real purchases. Nothing is saved." />
      <DealModel />
    </>
  );
}
