"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { SupplierForm } from "@/components/supplier-form";
import { Card, PageHeader } from "@/components/ui/core";
import { PermissionDenied } from "@/components/ui/states";
import { api, unwrap } from "@/lib/api";
import { can, useSession } from "@/lib/session";

export default function NewSupplierPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const session = useSession();
  if (!can(session, "edit_suppliers")) return <PermissionDenied />;
  return (
    <>
      <PageHeader title="Add supplier" />
      <Card>
        <SupplierForm
          submitLabel="Add supplier"
          chooseKind
          onSubmit={async (body) => {
            const s = unwrap(await api.POST("/api/v1/suppliers", { body: { ...body, kind: body.kind ?? "supplier" } }));
            await qc.invalidateQueries({ queryKey: ["suppliers"] });
            toast.success(`${s.name} added`);
            router.push(`/app/suppliers/${s.id}`);
          }}
        />
      </Card>
    </>
  );
}
