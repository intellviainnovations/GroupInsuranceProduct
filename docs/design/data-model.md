# Data model (logical)

- **Status:** Proposed, ready for the first build tasks. Any later change is a schema change and needs a human's approval (CLAUDE.md). Owner: architect.
- **Scope:** Phase 1, one insurer (USGIC Group Personal Accident, D-022), one bank deployment (D-020). Rules for types, sessions, jobs and audit: `docs/adr/0002-persistence-sessions-audit.md`.
- **Sources:** knowledge repo decisions D-022, D-023; `docs/contracts/` (the insurer, bank-auth and CBS contracts decide which columns exist).
- **Not here:** physical DDL. The backend builder writes Alembic migrations from this document.

## Type legend
`UUID` application-generated key. `STR(n)` variable text of at most n characters. `TEXT` long text. `INT`, `BIGINT`. `NUM(14,2)` money in INR. `BOOL`. `DATE` business date. `TS` timestamp with time zone, stored in UTC. `BLOB` binary. `FK` foreign key. `null` = nullable; everything else is `NOT NULL`. Empty strings are never stored; use NULL (ADR-0002).
All tables also have `created_at TS`; mutable tables have `updated_at TS` (not repeated below).

## Entity overview
```
branch ─< app_user >─< user_role >─ app_role         user_session >─ app_user
insurer ─< insurer_product ─< insurer_plan ─< plan_rate        pool_account >─ insurer
customer ─< customer_account
customer ─< enrolment >─ insurer_plan, plan_rate, insurer_product, branch, app_user (maker)
enrolment ─< enrolment_nominee      enrolment ─< enrolment_status_history
enrolment ─< cbs_posting >─ pool_account, customer_account
enrolment ─< insurer_call           enrolment ─< document
enrolment ─< endorsement ─< endorsement_change      enrolment ─< cancellation >─ cbs_posting
approval  (generic: points at an enrolment, endorsement or cancellation)
reconciliation_run ─< reconciliation_item >─ enrolment, cbs_posting
job, idempotency_key, login_throttle, app_setting, audit_event  (platform tables)
ref_code, insurer_code_map  (lookups)
```

## 1. Reference and configuration
| Table | Columns | Keys / constraints |
|---|---|---|
| `branch` | `branch_code` STR(10), `branch_name` STR(100), `region` STR(100) null, `ifsc` STR(11) null, `active` BOOL | PK `branch_code`. Maintained by an admin; the bank's branch master is not integrated in Phase 1 |
| `insurer` | `insurer_id` UUID, `code` STR(20), `name` STR(100), `active` BOOL | PK; unique `code` |
| `insurer_product` | `product_id` UUID, `insurer_id` FK, `product_code` STR(20) (the insurer's own code), `name` STR(100), `line` STR(10) (`GPA` in Phase 1), `active` BOOL | PK; unique (`insurer_id`, `product_code`) |
| `insurer_plan` | `plan_id` UUID, `product_id` FK, `plan_code` STR(10) (`A`, `B`, `C` for USGIC), `name` STR(100), `active` BOOL | PK; unique (`product_id`, `plan_code`) |
| `plan_rate` | `rate_id` UUID, `plan_id` FK, `effective_from` DATE, `effective_to` DATE null, `sum_insured` NUM, `net_premium` NUM, `gst_amount` NUM, `gross_premium` NUM, `policy_term_days` INT, `maintained_by` FK `app_user`, `approved_by` FK `app_user`, `note` STR(300) null | PK; CHECK `gross_premium = net_premium + gst_amount`; no overlapping periods per plan (application rule). **Human-maintained from the insurer's documents; we never calculate premium (Q30).** The insurer's returned premium is stored on the enrolment and compared to this row |
| `ref_code` | `category` STR(30), `code` STR(30), `label` STR(100), `sort_order` INT, `active` BOOL | PK (`category`, `code`). Categories: `GENDER`, `RELATION`, `OCCUPATION`, `STATE`, `CONSENT_METHOD`, `CANCEL_REASON` (`BRANCH` exists only in `insurer_code_map`, mapping the bank's branch code to the insurer's) |
| `insurer_code_map` | `insurer_id` FK, `category` STR(30), `our_code` STR(30), `insurer_value` STR(100) | PK (`insurer_id`, `category`, `our_code`). Turns our codes into the insurer's exact spelling (for example `Male` versus `MALE`) |
| `pool_account` | `pool_account_id` UUID, `insurer_id` FK, `product_id` FK null, `account_no` STR(30), `label` STR(100), `active_from` DATE, `active_to` DATE null | PK. The bank's collection account that is credited with each premium (D-023). Exactly one active per insurer product at a time |
| `app_role` | `role_id` UUID, `code` STR(30), `name` STR(100) | PK; unique `code`. Proposed roles: `BRANCH_USER` (maker), `CHECKER`, `OPERATIONS` (retries, reconciliation), `REPORT_VIEWER`, `ADMIN`, `AUDITOR` (read-only). Names to confirm (Q32) |
| `app_setting` | `setting_key` STR(80), `setting_value` STR(500), `updated_by` FK null | PK `setting_key`. For example whether maker-checker is on per action |

## 2. Identity and sessions
| Table | Columns | Keys / constraints |
|---|---|---|
| `app_user` | `user_id` UUID, `roll_no` STR(20), `display_name` STR(150) null, `email` STR(150) null, `branch_code` FK, `designation` STR(100) null, `status` STR(10) (`ACTIVE`, `DISABLED`), `first_login_at` TS null, `last_login_at` TS null | PK; unique `roll_no`. Created on first successful bank login with **no role**; an admin grants roles (Q32). Branch and designation are refreshed from the bank's response at each login. Passwords are never stored |
| `user_role` | `user_id` FK, `role_id` FK, `granted_by` FK `app_user`, `granted_at` TS, `revoked_at` TS null | PK (`user_id`, `role_id`) |
| `user_session` | `session_hash` STR(64), `user_id` FK, `branch_code` FK, `last_seen_at` TS, `idle_expires_at` TS, `absolute_expires_at` TS, `revoked_at` TS null, `revoke_reason` STR(30) null, `bank_session_enc` BLOB null, `client_ip` STR(45) null, `user_agent_hash` STR(64) null | PK `session_hash` (hash of the opaque cookie value). `bank_session_enc` is the bank ESB session reference, encrypted |
| `login_throttle` | `throttle_key` STR(100) (roll number or client address), `fail_count` INT, `window_start` TS, `locked_until` TS null | PK `throttle_key`. Request throttling (matrix C-28); lockout policy depends on Q29 |

## 3. Customer and sale
Customer details are **keyed by the branch user**; the CBS is not called for customer lookup (D-023). Repeat sales can reuse a saved customer by CIF.

| Table | Columns | Keys / constraints |
|---|---|---|
| `customer` | `customer_id` UUID, `bank_customer_id` STR(20) (CIF), `first_name` STR(60), `middle_name` STR(60) null, `last_name` STR(60), `gender_code` STR(30), `date_of_birth` DATE, `mobile` STR(15), `email` STR(150) null, `address1` STR(150), `address2` STR(150) null, `city` STR(60), `state_code` STR(30), `pincode` STR(6), `occupation_code` STR(30), `other_occupation` STR(60) null, `created_by` FK `app_user` | PK; unique `bank_customer_id` |
| `customer_account` | `customer_account_id` UUID, `customer_id` FK, `account_no_enc` BLOB, `account_no_hash` STR(64), `ifsc` STR(11) null, `branch_code` FK null, `active` BOOL | PK; unique (`customer_id`, `account_no_hash`). The debit account. Encrypted at application level, hash for exact lookup (ADR-0002) |
| `enrolment` | see below | The central record: one insured person, one proposal, one certificate |
| `enrolment_nominee` | `nominee_id` UUID, `enrolment_id` FK, `seq` INT, `name` STR(150), `date_of_birth` DATE null, `age` INT null, `relation_code` STR(30), `gender_code` STR(30) null, `mobile` STR(15) null, `email` STR(150) null, `present_address` STR(300) null, `permanent_address` STR(300) null, `share_percent` NUM(7,4), `bank_account_enc` BLOB null, `ifsc` STR(11) null, `bank_name` STR(100) null, `account_holder_name` STR(150) null, `appointee_name` STR(150) null, `appointee_relation_code` STR(30) null, `appointee_dob` DATE null, `appointee_age` INT null, `appointee_gender_code` STR(30) null | PK; unique (`enrolment_id`, `seq`). Shares add up to 100 (application rule and test) |
| `enrolment_status_history` | `history_id` UUID, `enrolment_id` FK, `from_status` STR(30) null, `to_status` STR(30), `reason` STR(300) null, `actor_user_id` FK null (null = system), `correlation_id` STR(40) null, `changed_at` TS | PK; index (`enrolment_id`, `changed_at`) |
| `approval` | `approval_id` UUID, `entity_type` STR(30) (`ENROLMENT`, `ENDORSEMENT`, `CANCELLATION`), `entity_id` UUID, `action` STR(30), `maker_user_id` FK, `checker_user_id` FK null, `status` STR(15) (`PENDING`, `APPROVED`, `REJECTED`, `WITHDRAWN`), `maker_comment` STR(300) null, `checker_comment` STR(300) null, `requested_at` TS, `decided_at` TS null | PK; CHECK `checker_user_id <> maker_user_id`; index (`entity_type`, `entity_id`) |

### `enrolment`
| Group | Columns |
|---|---|
| Identity | `enrolment_id` UUID PK; `our_reference_no` STR(30) unique (the reference we send to the insurer, generated by us); `status` STR(30) (values in `docs/specs/usgic-gpa-sale-flow.md`); `status_changed_at` TS; `version` INT (optimistic locking) |
| Links | `product_id` FK; `plan_id` FK; `rate_id` FK (rate version in force at sale); `customer_id` FK; `customer_account_id` FK; `branch_code` FK; `created_by` FK `app_user` (maker); `source_channel` STR(20) default `BRANCH`; `renewal_of_enrolment_id` FK null |
| Insured, as sent to the insurer (snapshot, never edited after submission; changes go through an endorsement) | `insured_first_name`, `insured_middle_name` null, `insured_last_name`, `insured_gender_code`, `insured_dob` DATE, `insured_mobile`, `insured_email` null, `insured_address1`, `insured_address2` null, `insured_city`, `insured_state_code`, `insured_pincode`, `insured_occupation_code`, `insured_other_occupation` null, `any_disability` BOOL, `disability_description` STR(500) null, `guardian_name_address` STR(500) null |
| Proposal | `insurer_proposal_no` STR(30) null, unique; `proposal_created_at` TS null |
| Premium, **as returned by the insurer** | `net_premium` NUM null, `gst_amount` NUM null, `gross_premium` NUM null, `premium_matches_rate` BOOL null (false raises a flag for a human) |
| Consent | `consent_method` STR(30) null, `consent_ref` STR(60) null, `consent_at` TS null (mechanism is open, Q28) |
| Certificate | `certificate_no` STR(40) null, unique; `risk_start_date` DATE null; `risk_end_date` DATE null; `issued_at` TS null |
| Closure | `cancelled_at` TS null; `cancel_reason_code` STR(30) null |

Indexes: (`branch_code`, `status`), (`created_by`, `status`), (`customer_id`), (`risk_end_date`) for renewal lists, (`status`, `status_changed_at`) for the in-process and attention queues.

## 4. Money and insurer calls
| Table | Columns | Keys / constraints |
|---|---|---|
| `cbs_posting` | `posting_id` UUID, `enrolment_id` FK, `kind` STR(20) (`PREMIUM`, `REFUND`, `REVERSAL`), `amount` NUM, `customer_account_id` FK, `pool_account_id` FK, `cbs_request_ref` STR(40), `cbs_tran_id` STR(40) null, `cbs_tran_at` TS null, `status` STR(15) (`PENDING`, `SUCCESS`, `FAILED`, `UNKNOWN`, `REVERSED`), `error_code` STR(40) null, `error_text` STR(300) null, `attempt_no` INT, `requested_at` TS, `completed_at` TS null, `reverses_posting_id` FK null, `created_by` FK null | PK; unique `cbs_request_ref` (our idempotency reference). **Assumption:** one CBS transaction with two legs (debit customer, credit pool); `REFUND` runs the other way (Q27). `UNKNOWN` means the call ended without a clear answer and must be checked with the CBS before any retry |
| `insurer_call` | `call_id` UUID, `insurer_id` FK, `enrolment_id` FK null, `operation` STR(40), `our_reference` STR(40) null, `attempt_no` INT, `status` STR(15) (`SUCCESS`, `REJECTED`, `ERROR`, `UNKNOWN`), `http_status` INT null, `insurer_status` STR(30) null, `error_description` STR(500) null, `correlation_id` STR(40) null, `started_at` TS, `finished_at` TS null, `duration_ms` INT null, `request_enc` BLOB null, `response_enc` BLOB null, `retain_until` DATE null | PK; index (`enrolment_id`, `started_at`). Payload columns are optional and encrypted; retention is open (Q31) |
| `document` | `document_id` UUID, `enrolment_id` FK, `kind` STR(20) (`COI`, `CONSENT_LETTER`, `ACKNOWLEDGEMENT`), `file_name` STR(150), `content_type` STR(80), `size_bytes` BIGINT, `sha256` STR(64), `content` BLOB, `source` STR(15) (`INSURER`, `UPLOAD`, `GENERATED`), `created_by` FK null | PK; index (`enrolment_id`, `kind`). The certificate PDF received from the insurer is stored as received |

## 5. After-sale changes
| Table | Columns | Keys / constraints |
|---|---|---|
| `endorsement` | `endorsement_id` UUID, `enrolment_id` FK, `requested_by` FK `app_user`, `approval_id` FK null, `status` STR(20) (`DRAFT`, `PENDING_CHECK`, `SUBMITTED`, `COMPLETED`, `REJECTED`, `FAILED`), `remarks` STR(500) null, `insurer_proposal_no` STR(30) null, `endorsed_certificate_no` STR(40) null, `completed_at` TS null | PK. What the insurer's endorsement call actually changes is unclear (Q26) |
| `endorsement_change` | `endorsement_id` FK, `field_name` STR(50), `old_value` STR(500) null, `new_value` STR(500) null | PK (`endorsement_id`, `field_name`) |
| `cancellation` | `cancellation_id` UUID, `enrolment_id` FK, `requested_by` FK `app_user`, `approval_id` FK null, `reason_code` STR(30), `status` STR(20) (`DRAFT`, `PENDING_CHECK`, `SUBMITTED`, `COMPLETED`, `REJECTED`, `FAILED`), `refund_amount` NUM null (as returned by the insurer), `refund_at` TS null, `refund_posting_id` FK null, `completed_at` TS null | PK. Refund rule (full or pro-rata) is open (Q26) |

## 6. Reconciliation and platform
| Table | Columns | Keys / constraints |
|---|---|---|
| `reconciliation_run` | `run_id` UUID, `business_date` DATE, `pool_account_id` FK, `started_by` FK null (null = scheduled), `status` STR(15), `started_at` TS, `finished_at` TS null, `total_items` INT, `matched_items` INT, `exception_items` INT | PK |
| `reconciliation_item` | `item_id` UUID, `run_id` FK, `enrolment_id` FK null, `posting_id` FK null, `expected_amount` NUM null, `actual_amount` NUM null, `result` STR(30) (`MATCHED`, `POSTED_NO_POLICY`, `POLICY_NO_POSTING`, `AMOUNT_MISMATCH`, `DUPLICATE_POSTING`), `status` STR(15) (`OPEN`, `RESOLVED`), `resolution_note` STR(500) null, `resolved_by` FK null, `resolved_at` TS null | PK; index (`run_id`, `result`). The case the whole design guards against: customer debited, no policy issued |
| `job` | `job_id` UUID, `job_type` STR(40), `entity_type` STR(30) null, `entity_id` UUID null, `dedupe_key` STR(100), `status` STR(10) (`QUEUED`, `RUNNING`, `DONE`, `FAILED`, `DEAD`), `run_after` TS, `attempts` INT, `max_attempts` INT, `locked_by` STR(60) null, `locked_at` TS null, `last_error` STR(500) null | PK; unique `dedupe_key`; index (`status`, `run_after`) |
| `idempotency_key` | `scope` STR(40), `idem_key` STR(80), `request_hash` STR(64), `resource_id` UUID null, `response_status` INT null, `expires_at` TS | PK (`scope`, `idem_key`) |
| `audit_event` | `audit_id` BIGINT (database sequence), `event_time` TS, `actor_user_id` UUID null, `actor_roll_no` STR(20) null, `branch_code` STR(10) null, `event_type` STR(50), `entity_type` STR(30) null, `entity_id` UUID null, `outcome` STR(10), `client_ip` STR(45) null, `correlation_id` STR(40) null, `detail` STR(1000) null, `prev_hash` STR(64), `row_hash` STR(64) | PK `audit_id`; append-only; the application's database role has insert and select only |

## 7. Data classification
| Class | Columns | Handling (ADR-0002, Q31) |
|---|---|---|
| P1 identifiers | `customer.bank_customer_id`, account numbers (`customer_account.account_no_enc`, `enrolment_nominee.bank_account_enc`), `cbs_posting.cbs_tran_id` | Account numbers encrypted in the application; hashes for lookup; never logged |
| P2 personal | names, dates of birth, mobile, email, addresses, occupation, disability, nominee and appointee details, `endorsement_change` values, consent references | Database/disk encryption and role-based access; excluded from logs and audit details |
| P3 business | amounts, statuses, references, rates, branch data, timestamps | Normal handling |
| Secrets | bank and insurer credentials, encryption keys, tokens | Never in the database or the repo; held in the bank's secret store or protected configuration |

## 8. Open points that may change the model
| Open point | Effect |
|---|---|
| Q27 CBS contract: one two-leg transaction or two calls, reversal and statement formats | `cbs_posting` shape and the reconciliation inputs |
| Q26 endorsement and cancellation behaviour, renewal call | `endorsement`, `cancellation`, `renewal_of_enrolment_id` |
| Q28 customer consent mechanism and SMS gateway | `consent_*` columns, possibly an `otp_challenge` table |
| Q30 plan rates and who maintains them | `plan_rate` workflow |
| Q31 retention and personal-data rules | purge jobs, payload retention |
| Q32 role list and maker-checker scope | `app_role` seed data, `approval.action` values |
| D-015 master policyholder (Q3) | Possibly a `group_policy` table if the insurer's certificate depends on a master policy number |
