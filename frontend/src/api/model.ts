// UI-side names derived from the generated contract types (./types.ts).
// Hand-written on purpose: these are aliases and helpers only, never new shapes.
import type { Approval, Error as ErrorSchema, EnrolmentDetail, EnrolmentSummary, Me, Outcome, RefCodeItem } from "./types";

export type * from "./types";

export type EnrolmentStatus = EnrolmentSummary["status"];
export type Role = Me["roles"][number];
export type AllowedAction = EnrolmentDetail["allowed_actions"][number];
export type AttentionReason = NonNullable<EnrolmentSummary["attention_reason"]>;
export type OutcomeResult = Outcome["result"];
export type ErrorBody = ErrorSchema;
export type ErrorCode = ErrorSchema["code"];
export type ApprovalAction = Approval["action"];
export type ApprovalStatus = Approval["status"];
export type RefCode = RefCodeItem;

// Display order for status filters. The Record type makes the compiler
// fail if the contract adds or removes a status.
const statusOrder: Record<EnrolmentStatus, number> = {
  DRAFT: 1,
  PENDING_CHECK: 2,
  REJECTED: 3,
  APPROVED: 4,
  PROPOSAL_CREATED: 5,
  PAYMENT_PENDING: 6,
  PAYMENT_FAILED: 7,
  PAID: 8,
  ISSUED: 9,
  PROPOSAL_REJECTED: 10,
  PROPOSAL_CANCELLED: 11,
  NEEDS_ATTENTION: 12,
  CANCELLATION_PENDING: 13,
  CANCELLED: 14,
};
export const ENROLMENT_STATUSES = (Object.keys(statusOrder) as EnrolmentStatus[]).sort((a, b) => statusOrder[a] - statusOrder[b]);
