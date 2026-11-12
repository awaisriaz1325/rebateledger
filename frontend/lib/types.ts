/** Aliases of generated API schema types (never hand-written duplicates). */
import type { components } from "@/generated/api";

type S = components["schemas"];
export type Supplier = S["SupplierOut"];
export type SupplierDetail = S["SupplierDetail"];
export type Agreement = S["AgreementOut"];
export type AgreementDetail = S["AgreementDetail"];
export type Version = S["VersionOut"];
export type Terms = S["VersionTermsIn"];
export type TermsCheck = S["TermsCheckOut"];
export type Batch = S["BatchOut"];
export type ImportPreview = S["ImportPreviewOut"];
export type Run = S["RunOut"];
export type PeriodResult = S["PeriodResultOut"];
export type ResultDetail = S["ResultDetail"];
export type PreviewResult = S["PreviewResultOut"];
export type ReconRow = S["ReconRow"];
export type Credit = S["CreditOut"];
export type CreditDetail = S["CreditDetail"];
export type Unmatched = S["UnmatchedOut"];
export type Claim = S["ClaimOut"];
export type ClaimDetail = S["ClaimDetail"];
export type Approval = S["ApprovalOut"];
export type TierRow = S["TierOut"];
export type Member = S["MemberOut"];
export type ExportRecord = S["ExportOut"];
export type ReportInfo = S["ReportInfo"];
export type ReportPreview = S["ReportPreviewOut"];
