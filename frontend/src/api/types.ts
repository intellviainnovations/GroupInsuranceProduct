// Hand-maintained types matching docs/contracts/staff-api.openapi.yaml
// (components.schemas). Keep names and fields identical to the contract.
// Money and Percent are decimal strings; never convert them to numbers for logic.

export type Uuid = string;
export type Money = string;
export type Percent = string;
export type Nullable<T> = T | null;

export const ENROLMENT_STATUSES = [
  "DRAFT",
  "PENDING_CHECK",
  "REJECTED",
  "APPROVED",
  "PROPOSAL_CREATED",
  "PAYMENT_PENDING",
  "PAYMENT_FAILED",
  "PAID",
  "ISSUED",
  "PROPOSAL_REJECTED",
  "PROPOSAL_CANCELLED",
  "NEEDS_ATTENTION",
  "CANCELLATION_PENDING",
  "CANCELLED",
] as const;
export type EnrolmentStatus = (typeof ENROLMENT_STATUSES)[number];

export type Role = "BRANCH_USER" | "CHECKER" | "OPERATIONS" | "REPORT_VIEWER" | "ADMIN" | "AUDITOR";

export type AllowedAction =
  | "EDIT"
  | "SUBMIT"
  | "CREATE_PROPOSAL"
  | "RECORD_CONSENT"
  | "POST_PAYMENT"
  | "RETRY_ISSUE"
  | "REOPEN"
  | "ABANDON"
  | "COPY"
  | "DOWNLOAD_CERTIFICATE"
  | "REQUEST_CANCELLATION"
  | "APPROVE"
  | "REJECT"
  | "RESOLVE";

export type AttentionReason =
  | "POSTING_UNKNOWN"
  | "ISSUE_RETRIES_EXHAUSTED"
  | "ISSUE_UNKNOWN"
  | "PROPOSAL_UNKNOWN"
  | "CANCEL_UNKNOWN";

export type ErrorCode =
  | "VALIDATION_FAILED"
  | "UNAUTHENTICATED"
  | "LOGIN_FAILED"
  | "CSRF_FAILED"
  | "FORBIDDEN"
  | "MAKER_CANNOT_CHECK"
  | "NOT_FOUND"
  | "CUSTOMER_NOT_FOUND"
  | "INVALID_STATE"
  | "VERSION_CONFLICT"
  | "IDEMPOTENCY_KEY_REUSED"
  | "IDEMPOTENCY_IN_PROGRESS"
  | "PREMIUM_MISMATCH"
  | "CONSENT_REQUIRED"
  | "ACCOUNT_NOT_ELIGIBLE"
  | "POSTING_UNRESOLVED"
  | "CBS_UNAVAILABLE"
  | "AUTH_UNAVAILABLE"
  | "SERVICE_UNAVAILABLE"
  | "RATE_LIMITED"
  | "INTERNAL";

export type FieldErrorCode =
  | "REQUIRED"
  | "TOO_LONG"
  | "INVALID_FORMAT"
  | "INVALID_CODE"
  | "OUT_OF_RANGE"
  | "SHARES_NOT_100"
  | "NOT_ALLOWED"
  | "CBS_SOURCED_READ_ONLY"
  | "ACCOUNT_NOT_OF_CUSTOMER"
  | "ACCOUNT_NOT_SELECTABLE";

export interface FieldError {
  field: string;
  code: FieldErrorCode;
  message?: string;
}

export interface ErrorBody {
  error: string;
  code: ErrorCode;
  correlation_id: Nullable<string>;
  fields?: FieldError[];
}

// ---------- auth ----------
export interface LoginRequest {
  branch_code: string;
  roll_no: string;
  password: string;
}
export interface OtpRequest {
  challenge_id: Uuid;
  otp: string;
}
export interface LoginResult {
  status: "SIGNED_IN" | "OTP_REQUIRED";
  challenge_id?: Uuid;
  challenge_expires_at?: string;
  me?: Me;
}
export interface Branch {
  code: string;
  name?: Nullable<string>;
}
export interface Me {
  user_id: Uuid;
  roll_no: string;
  display_name?: Nullable<string>;
  designation?: Nullable<string>;
  branch: Branch;
  roles: Role[];
  cross_branch?: boolean;
  csrf_token: string;
  session: { idle_expires_at: string; absolute_expires_at: string };
  environment: { mode: "dev" | "demo" | "uat" | "prod"; synthetic_data: boolean };
  settings: { maker_checker_enrolment: boolean; maker_checker_cancellation: boolean };
}

// ---------- reference ----------
export interface RefCode {
  code: string;
  label: string;
}
export type RefCodeList = RefCode[];
export interface RefCodes {
  GENDER: RefCodeList;
  RELATION: RefCodeList;
  OCCUPATION: RefCodeList;
  STATE: RefCodeList;
  CONSENT_METHOD: RefCodeList;
  CANCEL_REASON: RefCodeList;
}
export interface PlanRate {
  rate_id: Uuid;
  sum_insured: Money;
  net_premium: Money;
  gst_amount: Money;
  gross_premium: Money;
  policy_term_days: number;
  effective_from: string;
  synthetic: boolean;
  note?: Nullable<string>;
}
export interface Plan {
  plan_code: string;
  name: string;
  rate: Nullable<PlanRate>;
}

// ---------- customer lookup ----------
export type CustomerLookupRequest = { account_no: string } | { cif: string };
export interface CbsCustomer {
  cif_masked: string;
  first_name: string;
  middle_name?: Nullable<string>;
  last_name: string;
  gender_code?: Nullable<string>;
  date_of_birth?: Nullable<string>;
  mobile_masked?: Nullable<string>;
  city?: Nullable<string>;
  state_code?: Nullable<string>;
  kyc_status?: Nullable<string>;
  customer_status?: Nullable<string>;
  home_branch_code?: Nullable<string>;
}
export interface CbsAccount {
  account_key: string;
  account_no_masked: string;
  account_type?: Nullable<string>;
  account_status?: Nullable<string>;
  branch_code?: Nullable<string>;
  joint_account?: Nullable<boolean>;
  holder_name?: Nullable<string>;
  selectable: boolean;
}
export interface CustomerLookupResult {
  customer: CbsCustomer;
  accounts: CbsAccount[];
  fetched_at: string;
}

// ---------- enrolment input ----------
export interface DraftCreate {
  lookup: CustomerLookupRequest;
  debit_account_key: string;
  plan_code?: string;
}
export interface InsuredInput {
  first_name?: string;
  middle_name?: Nullable<string>;
  last_name?: string;
  gender_code?: string;
  date_of_birth?: string;
  mobile?: string;
  email?: Nullable<string>;
  address1?: string;
  address2?: Nullable<string>;
  city?: string;
  state_code?: string;
  pincode?: string;
  occupation_code?: string;
  other_occupation?: Nullable<string>;
  any_disability?: boolean;
  disability_description?: Nullable<string>;
  guardian_name_address?: Nullable<string>;
}
export interface NomineeInput {
  name: string;
  relation_code: string;
  share_percent: Percent;
  date_of_birth?: Nullable<string>;
  age?: Nullable<number>;
  gender_code?: Nullable<string>;
  mobile?: Nullable<string>;
  email?: Nullable<string>;
  present_address?: Nullable<string>;
  permanent_address?: Nullable<string>;
  bank_account_no?: Nullable<string>;
  ifsc?: Nullable<string>;
  bank_name?: Nullable<string>;
  account_holder_name?: Nullable<string>;
  appointee_name?: Nullable<string>;
  appointee_relation_code?: Nullable<string>;
  appointee_dob?: Nullable<string>;
  appointee_age?: Nullable<number>;
  appointee_gender_code?: Nullable<string>;
}
export interface DraftPatch {
  version: number;
  debit_account_key?: string;
  plan_code?: string;
  insured?: InsuredInput;
  nominees?: NomineeInput[];
}
export interface VersionOnly {
  version: number;
}
export interface SubmitRequest {
  version: number;
  comment?: Nullable<string>;
}
export interface CommentedVersion {
  version: number;
  comment: string;
}
export interface ConsentRequest {
  version: number;
  method: string;
  reference: string;
  confirmed_amount?: Money;
}
export interface CancellationRequest {
  version: number;
  reason_code: string;
  remarks?: Nullable<string>;
}
export interface DecisionRequest {
  comment?: Nullable<string>;
}
export interface RejectRequest {
  comment: string;
}
export interface ResolveRequest {
  version: number;
  action: "RECHECK" | "CONFIRM";
  target_status?: "PAID" | "PAYMENT_FAILED";
  note?: string;
  evidence_ref?: Nullable<string>;
}

// ---------- enrolment output ----------
export type OutcomeResult = "DONE" | "REJECTED" | "QUEUED_FOR_RETRY" | "NEEDS_ATTENTION" | "PENDING_APPROVAL";
export interface ActionResult {
  enrolment: EnrolmentDetail;
  outcome: {
    result: OutcomeResult;
    category?: Nullable<string>;
    message?: Nullable<string>;
    replayed?: boolean;
  };
}
export interface UserRef {
  user_id: Uuid;
  roll_no: string;
  display_name?: Nullable<string>;
}
export interface EnrolmentSummary {
  enrolment_id: Uuid;
  our_reference_no: string;
  status: EnrolmentStatus;
  status_changed_at: string;
  created_at: string;
  branch_code: string;
  insured_name: string;
  plan_code?: Nullable<string>;
  gross_premium?: Nullable<Money>;
  insurer_proposal_no?: Nullable<string>;
  certificate_no?: Nullable<string>;
  created_by: UserRef;
  attention_reason?: Nullable<AttentionReason>;
}
export interface Paged<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}
export type EnrolmentPage = Paged<EnrolmentSummary>;
export interface Insured extends InsuredInput {
  cbs_sourced_fields: string[];
}
export interface Nominee extends NomineeInput {
  seq: number;
  bank_account_masked?: Nullable<string>;
}
export interface Posting {
  posting_id: Uuid;
  kind: "PREMIUM" | "REFUND" | "REVERSAL";
  amount: Money;
  status: "PENDING" | "SUCCESS" | "FAILED" | "UNKNOWN" | "REVERSED";
  cbs_request_ref: string;
  cbs_tran_id_masked?: Nullable<string>;
  cbs_tran_at?: Nullable<string>;
  attempt_no: number;
  error_code?: Nullable<string>;
  requested_at: string;
  completed_at?: Nullable<string>;
}
export interface InsurerCall {
  operation: string;
  attempt_no: number;
  status: "SUCCESS" | "REJECTED" | "ERROR" | "UNKNOWN";
  error_category?: Nullable<string>;
  started_at: string;
  duration_ms?: Nullable<number>;
}
export interface StatusChange {
  from_status?: Nullable<EnrolmentStatus>;
  to_status: EnrolmentStatus;
  reason?: Nullable<string>;
  actor?: Nullable<UserRef>;
  correlation_id?: Nullable<string>;
  changed_at: string;
}
export interface EnrolmentDocument {
  document_id: Uuid;
  kind: "COI" | "CONSENT_LETTER" | "ACKNOWLEDGEMENT";
  file_name: string;
  size_bytes: number;
  created_at: string;
}
export interface EnrolmentDetail {
  enrolment_id: Uuid;
  our_reference_no: string;
  status: EnrolmentStatus;
  status_changed_at: string;
  version: number;
  branch: Branch;
  created_by: UserRef;
  created_at: string;
  updated_at?: string;
  customer: { customer_id: Uuid; cif_masked: string; cbs_fetched_at: Nullable<string> };
  debit_account: CbsAccount;
  insured: Insured;
  nominees: Nominee[];
  plan?: Nullable<Plan>;
  proposal?: Nullable<{ insurer_proposal_no: string; created_at: string }>;
  premium?: Nullable<{ net_premium: Money; gst_amount: Money; gross_premium: Money; matches_rate: boolean }>;
  consent?: Nullable<{ method: string; reference: string; consented_at: string }>;
  certificate?: Nullable<{
    certificate_no: string;
    risk_start_date: string;
    risk_end_date: string;
    issued_at: string;
    pdf_available: boolean;
  }>;
  postings: Posting[];
  insurer_calls: InsurerCall[];
  status_history: StatusChange[];
  approvals: Approval[];
  documents: EnrolmentDocument[];
  cancellation?: Nullable<{
    cancellation_id: Uuid;
    reason_code: string;
    status: "DRAFT" | "PENDING_CHECK" | "SUBMITTED" | "COMPLETED" | "REJECTED" | "FAILED";
    requested_by: UserRef;
    requested_at: string;
    refund_amount?: Nullable<Money>;
    completed_at?: Nullable<string>;
  }>;
  attention?: Nullable<{ reason: AttentionReason; since: string }>;
  allowed_actions: AllowedAction[];
}

// ---------- approvals ----------
export type ApprovalAction = "SUBMIT_SALE" | "CANCEL_CERTIFICATE" | "ATTENTION_RESOLVE";
export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "WITHDRAWN";
export interface Approval {
  approval_id: Uuid;
  entity_type: "ENROLMENT" | "CANCELLATION";
  entity_id: Uuid;
  enrolment_id?: Uuid;
  our_reference_no?: string;
  insured_name?: string;
  action: ApprovalAction;
  proposed_status?: Nullable<"PAID" | "PAYMENT_FAILED">;
  evidence_ref?: Nullable<string>;
  status: ApprovalStatus;
  maker: UserRef;
  checker?: Nullable<UserRef>;
  maker_comment?: Nullable<string>;
  checker_comment?: Nullable<string>;
  requested_at: string;
  decided_at?: Nullable<string>;
  can_decide: boolean;
}
export type ApprovalPage = Paged<Approval>;

// ---------- dashboard ----------
export interface Dashboard {
  as_of: string;
  scope: { all_branches: boolean; branch_code?: Nullable<string> };
  kpis: {
    issued_today: number;
    issued_month: number;
    gross_premium_today: Money;
    gross_premium_month: Money;
    in_process: number;
    drafts: number;
    pending_approvals: number;
    needs_attention: number;
  };
  queues?: {
    my_drafts?: EnrolmentSummary[];
    in_process?: EnrolmentSummary[];
    awaiting_my_approval?: Approval[];
    needs_attention?: EnrolmentSummary[];
    recently_issued?: EnrolmentSummary[];
  };
}
