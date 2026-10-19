// GENERATED FILE - DO NOT EDIT.
// Source: docs/contracts/staff-api.openapi.snapshot.json
// Regenerate with `npm run gen:api`; CI runs `npm run check:api`.
// UI-only helper types live in ./model.ts.

export interface ActionResult {
  enrolment: EnrolmentDetail;
  outcome: Outcome;
}

export interface Approval {
  action: "SUBMIT_SALE" | "CANCEL_CERTIFICATE" | "ATTENTION_RESOLVE";
  approval_id: string;
  can_decide: boolean;
  checker?: UserRef | null;
  checker_comment?: string | null;
  decided_at?: string | null;
  enrolment_id?: string | null;
  entity_id: string;
  entity_type: "ENROLMENT" | "CANCELLATION";
  evidence_ref?: string | null;
  insured_name?: string | null;
  maker: UserRef;
  maker_comment?: string | null;
  our_reference_no?: string | null;
  proposed_status?: "PAID" | "PAYMENT_FAILED" | null;
  requested_at: string;
  status: "PENDING" | "APPROVED" | "REJECTED" | "WITHDRAWN";
}

export interface ApprovalPage {
  items: Approval[];
  page: number;
  page_size: number;
  total: number;
}

export interface AttentionInfo {
  reason: "POSTING_UNKNOWN" | "ISSUE_RETRIES_EXHAUSTED" | "ISSUE_UNKNOWN" | "PROPOSAL_UNKNOWN" | "CANCEL_UNKNOWN";
  since: string;
}

export interface Branch {
  code: string;
  name?: string | null;
}

export interface CancellationInfo {
  cancellation_id: string;
  completed_at?: string | null;
  reason_code: string;
  refund_amount?: string | null;
  requested_at: string;
  requested_by: UserRef;
  status: "DRAFT" | "PENDING_CHECK" | "SUBMITTED" | "COMPLETED" | "REJECTED" | "FAILED";
}

export interface CancellationRequest {
  reason_code: string;
  remarks?: string | null;
  version: number;
}

export interface CbsAccount {
  account_key: string;
  account_no_masked: string;
  account_status?: string | null;
  account_type?: string | null;
  branch_code?: string | null;
  holder_name?: string | null;
  joint_account?: boolean | null;
  selectable: boolean;
}

export interface CbsCustomer {
  cif_masked: string;
  city?: string | null;
  customer_status?: string | null;
  date_of_birth?: string | null;
  first_name: string;
  gender_code?: string | null;
  home_branch_code?: string | null;
  kyc_status?: string | null;
  last_name: string;
  middle_name?: string | null;
  mobile_masked?: string | null;
  state_code?: string | null;
}

export interface CertificateInfo {
  certificate_no: string;
  issued_at: string;
  pdf_available: boolean;
  risk_end_date: string;
  risk_start_date: string;
}

export interface CommentedVersion {
  comment: string;
  version: number;
}

export interface Consent {
  consented_at: string;
  method: string;
  reference: string;
}

export interface ConsentRequest {
  confirmed_amount?: string | null;
  method: string;
  reference: string;
  version: number;
}

/** Exactly one of ``account_no`` and ``cif``. */
export interface CustomerLookupRequest {
  account_no?: string | null;
  cif?: string | null;
}

export interface CustomerLookupResult {
  accounts: CbsAccount[];
  customer: CbsCustomer;
  fetched_at: string;
}

export interface Dashboard {
  as_of: string;
  kpis: DashboardKpis;
  queues?: DashboardQueues | null;
  scope: DashboardScope;
}

export interface DashboardKpis {
  drafts: number;
  gross_premium_month: string;
  gross_premium_today: string;
  in_process: number;
  issued_month: number;
  issued_today: number;
  needs_attention: number;
  pending_approvals: number;
}

export interface DashboardQueues {
  awaiting_my_approval?: Approval[] | null;
  in_process?: EnrolmentSummary[] | null;
  my_drafts?: EnrolmentSummary[] | null;
  needs_attention?: EnrolmentSummary[] | null;
  recently_issued?: EnrolmentSummary[] | null;
}

export interface DashboardScope {
  all_branches: boolean;
  branch_code?: string | null;
}

export interface DecisionRequest {
  comment?: string | null;
}

export interface DocumentItem {
  created_at: string;
  document_id: string;
  file_name: string;
  kind: "COI" | "CONSENT_LETTER" | "ACKNOWLEDGEMENT";
  size_bytes: number;
}

export interface DraftCreate {
  debit_account_key: string;
  lookup: CustomerLookupRequest;
  plan_code?: string | null;
}

export interface DraftPatch {
  debit_account_key?: string | null;
  insured?: InsuredInput | null;
  nominees?: NomineeInput[] | null;
  plan_code?: string | null;
  version: number;
}

export interface EnrolmentCustomer {
  cbs_fetched_at: string | null;
  cif_masked: string;
  customer_id: string;
}

export interface EnrolmentDetail {
  allowed_actions: ("EDIT" | "SUBMIT" | "CREATE_PROPOSAL" | "RECORD_CONSENT" | "POST_PAYMENT" | "RETRY_ISSUE" | "REOPEN" | "ABANDON" | "COPY" | "DOWNLOAD_CERTIFICATE" | "REQUEST_CANCELLATION" | "APPROVE" | "REJECT" | "RESOLVE")[];
  approvals: Approval[];
  attention?: AttentionInfo | null;
  branch: Branch;
  cancellation?: CancellationInfo | null;
  certificate?: CertificateInfo | null;
  consent?: Consent | null;
  created_at: string;
  created_by: UserRef;
  customer: EnrolmentCustomer;
  debit_account: CbsAccount;
  documents: DocumentItem[];
  enrolment_id: string;
  insured: Insured;
  insurer_calls: InsurerCallItem[];
  nominees: Nominee[];
  our_reference_no: string;
  plan?: Plan | null;
  postings: PostingItem[];
  premium?: Premium | null;
  proposal?: Proposal | null;
  status: "DRAFT" | "PENDING_CHECK" | "REJECTED" | "APPROVED" | "PROPOSAL_CREATED" | "PAYMENT_PENDING" | "PAYMENT_FAILED" | "PAID" | "ISSUED" | "PROPOSAL_REJECTED" | "PROPOSAL_CANCELLED" | "NEEDS_ATTENTION" | "CANCELLATION_PENDING" | "CANCELLED";
  status_changed_at: string;
  status_history: StatusHistoryItem[];
  updated_at?: string | null;
  version: number;
}

export interface EnrolmentPage {
  items: EnrolmentSummary[];
  page: number;
  page_size: number;
  total: number;
}

export interface EnrolmentSummary {
  attention_reason?: "POSTING_UNKNOWN" | "ISSUE_RETRIES_EXHAUSTED" | "ISSUE_UNKNOWN" | "PROPOSAL_UNKNOWN" | "CANCEL_UNKNOWN" | null;
  branch_code: string;
  certificate_no?: string | null;
  created_at: string;
  created_by: UserRef;
  enrolment_id: string;
  gross_premium?: string | null;
  insured_name: string;
  insurer_proposal_no?: string | null;
  our_reference_no: string;
  plan_code?: string | null;
  status: "DRAFT" | "PENDING_CHECK" | "REJECTED" | "APPROVED" | "PROPOSAL_CREATED" | "PAYMENT_PENDING" | "PAYMENT_FAILED" | "PAID" | "ISSUED" | "PROPOSAL_REJECTED" | "PROPOSAL_CANCELLED" | "NEEDS_ATTENTION" | "CANCELLATION_PENDING" | "CANCELLED";
  status_changed_at: string;
}

export interface Error {
  code: "VALIDATION_FAILED" | "UNAUTHENTICATED" | "LOGIN_FAILED" | "CSRF_FAILED" | "FORBIDDEN" | "MAKER_CANNOT_CHECK" | "NOT_FOUND" | "CUSTOMER_NOT_FOUND" | "INVALID_STATE" | "VERSION_CONFLICT" | "IDEMPOTENCY_KEY_REUSED" | "IDEMPOTENCY_IN_PROGRESS" | "PREMIUM_MISMATCH" | "CONSENT_REQUIRED" | "ACCOUNT_NOT_ELIGIBLE" | "POSTING_UNRESOLVED" | "CBS_UNAVAILABLE" | "AUTH_UNAVAILABLE" | "SERVICE_UNAVAILABLE" | "RATE_LIMITED" | "INTERNAL";
  correlation_id: string | null;
  error: string;
  fields?: FieldError[] | null;
}

export interface FieldError {
  code: "REQUIRED" | "TOO_LONG" | "INVALID_FORMAT" | "INVALID_CODE" | "OUT_OF_RANGE" | "SHARES_NOT_100" | "NOT_ALLOWED" | "CBS_SOURCED_READ_ONLY" | "ACCOUNT_NOT_OF_CUSTOMER" | "ACCOUNT_NOT_SELECTABLE";
  field: string;
  message?: string | null;
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

export interface HealthResponse {
  status: string;
}

export interface Insured {
  address1?: string | null;
  address2?: string | null;
  any_disability?: boolean | null;
  cbs_sourced_fields: string[];
  city?: string | null;
  date_of_birth?: string | null;
  disability_description?: string | null;
  email?: string | null;
  first_name?: string | null;
  gender_code?: string | null;
  guardian_name_address?: string | null;
  last_name?: string | null;
  middle_name?: string | null;
  mobile?: string | null;
  occupation_code?: string | null;
  other_occupation?: string | null;
  pincode?: string | null;
  state_code?: string | null;
}

export interface InsuredInput {
  address1?: string | null;
  address2?: string | null;
  any_disability?: boolean | null;
  city?: string | null;
  date_of_birth?: string | null;
  disability_description?: string | null;
  email?: string | null;
  first_name?: string | null;
  gender_code?: string | null;
  guardian_name_address?: string | null;
  last_name?: string | null;
  middle_name?: string | null;
  mobile?: string | null;
  occupation_code?: string | null;
  other_occupation?: string | null;
  pincode?: string | null;
  state_code?: string | null;
}

export interface InsurerCallItem {
  attempt_no: number;
  duration_ms?: number | null;
  error_category?: string | null;
  operation: string;
  started_at: string;
  status: "SUCCESS" | "REJECTED" | "ERROR" | "UNKNOWN";
}

export interface LoginRequest {
  branch_code: string;
  password: string;
  roll_no: string;
}

export interface LoginResult {
  challenge_expires_at?: string | null;
  challenge_id?: string | null;
  me?: Me | null;
  status: "SIGNED_IN" | "OTP_REQUIRED";
}

export interface Me {
  branch: Branch;
  cross_branch?: boolean;
  csrf_token: string;
  designation?: string | null;
  display_name?: string | null;
  environment: MeEnvironment;
  roles: ("BRANCH_USER" | "CHECKER" | "OPERATIONS" | "REPORT_VIEWER" | "ADMIN" | "AUDITOR")[];
  roll_no: string;
  session: MeSession;
  settings: MeSettings;
  user_id: string;
}

export interface MeEnvironment {
  mode: "dev" | "demo" | "uat" | "prod";
  synthetic_data: boolean;
}

export interface MeSession {
  absolute_expires_at: string;
  idle_expires_at: string;
}

export interface MeSettings {
  maker_checker_cancellation: boolean;
  maker_checker_enrolment: boolean;
}

export interface Nominee {
  account_holder_name?: string | null;
  age?: number | null;
  appointee_age?: number | null;
  appointee_dob?: string | null;
  appointee_gender_code?: string | null;
  appointee_name?: string | null;
  appointee_relation_code?: string | null;
  bank_account_masked?: string | null;
  bank_account_no?: string | null;
  bank_name?: string | null;
  date_of_birth?: string | null;
  email?: string | null;
  gender_code?: string | null;
  ifsc?: string | null;
  mobile?: string | null;
  name: string;
  permanent_address?: string | null;
  present_address?: string | null;
  relation_code: string;
  seq: number;
  share_percent: string;
}

export interface NomineeInput {
  account_holder_name?: string | null;
  age?: number | null;
  appointee_age?: number | null;
  appointee_dob?: string | null;
  appointee_gender_code?: string | null;
  appointee_name?: string | null;
  appointee_relation_code?: string | null;
  bank_account_no?: string | null;
  bank_name?: string | null;
  date_of_birth?: string | null;
  email?: string | null;
  gender_code?: string | null;
  ifsc?: string | null;
  mobile?: string | null;
  name: string;
  permanent_address?: string | null;
  present_address?: string | null;
  relation_code: string;
  share_percent: string;
}

export interface OtpRequest {
  challenge_id: string;
  otp: string;
}

export interface Outcome {
  category?: "VALIDATION" | "AUTH" | "NOT_FOUND" | "BUSINESS_RULE" | "UNAVAILABLE" | "TIMEOUT" | "UNKNOWN" | "CBS_DECLINED" | null;
  message?: string | null;
  replayed?: boolean;
  result: "DONE" | "REJECTED" | "QUEUED_FOR_RETRY" | "NEEDS_ATTENTION" | "PENDING_APPROVAL";
}

export interface Plan {
  name: string;
  plan_code: string;
  rate: PlanRate | null;
}

export interface PlanList {
  items: Plan[];
}

export interface PlanRate {
  effective_from: string;
  gross_premium: string;
  gst_amount: string;
  net_premium: string;
  note?: string | null;
  policy_term_days: number;
  rate_id: string;
  sum_insured: string;
  synthetic: boolean;
}

export interface PostingItem {
  amount: string;
  attempt_no: number;
  cbs_request_ref: string;
  cbs_tran_at?: string | null;
  cbs_tran_id_masked?: string | null;
  completed_at?: string | null;
  error_code?: string | null;
  kind: "PREMIUM" | "REFUND" | "REVERSAL";
  posting_id: string;
  requested_at: string;
  status: "PENDING" | "SUCCESS" | "FAILED" | "UNKNOWN" | "REVERSED";
}

export interface Premium {
  gross_premium: string;
  gst_amount: string;
  matches_rate: boolean;
  net_premium: string;
}

export interface Proposal {
  created_at: string;
  insurer_proposal_no: string;
}

export interface ReadyResponse {
  checks: Record<string, string>;
  ready: boolean;
}

export interface RefCodeItem {
  code: string;
  label: string;
}

export interface RefCodes {
  CANCEL_REASON: RefCodeItem[];
  CONSENT_METHOD: RefCodeItem[];
  GENDER: RefCodeItem[];
  OCCUPATION: RefCodeItem[];
  RELATION: RefCodeItem[];
  STATE: RefCodeItem[];
}

export interface RejectRequest {
  comment: string;
}

export interface ResolveRequest {
  action: "RECHECK" | "CONFIRM";
  evidence_ref?: string | null;
  note?: string | null;
  target_status?: "PAID" | "PAYMENT_FAILED" | null;
  version: number;
}

export interface StatusHistoryItem {
  actor?: UserRef | null;
  changed_at: string;
  correlation_id?: string | null;
  from_status?: "DRAFT" | "PENDING_CHECK" | "REJECTED" | "APPROVED" | "PROPOSAL_CREATED" | "PAYMENT_PENDING" | "PAYMENT_FAILED" | "PAID" | "ISSUED" | "PROPOSAL_REJECTED" | "PROPOSAL_CANCELLED" | "NEEDS_ATTENTION" | "CANCELLATION_PENDING" | "CANCELLED" | null;
  reason?: string | null;
  to_status: "DRAFT" | "PENDING_CHECK" | "REJECTED" | "APPROVED" | "PROPOSAL_CREATED" | "PAYMENT_PENDING" | "PAYMENT_FAILED" | "PAID" | "ISSUED" | "PROPOSAL_REJECTED" | "PROPOSAL_CANCELLED" | "NEEDS_ATTENTION" | "CANCELLATION_PENDING" | "CANCELLED";
}

export interface SubmitRequest {
  comment?: string | null;
  version: number;
}

export interface UserRef {
  display_name?: string | null;
  roll_no: string;
  user_id: string;
}

export interface ValidationError {
  ctx?: Record<string, unknown>;
  input?: unknown;
  loc: (string | number)[];
  msg: string;
  type: string;
}

export interface VersionOnly {
  version: number;
}
