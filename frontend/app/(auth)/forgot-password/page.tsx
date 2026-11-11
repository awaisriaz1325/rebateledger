import type { Metadata } from "next";
import { ForgotPasswordForm } from "@/components/auth-forms";

export const metadata: Metadata = { title: "Reset password", robots: { index: false } };

export default function Page() {
  return <ForgotPasswordForm />;
}
