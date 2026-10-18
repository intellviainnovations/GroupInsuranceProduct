# Repository ports, unit of work, in-memory backend and synthetic seed

- **Status:** Proposed (architect, 2026-10-18), following the product owner's decisions of 2026-10-18 (Decided): demo app on the real FastAPI backend, in-memory synthetic data now, SQLAlchemy later (T-002) behind the same ports; real USGIC UAT adapter behind a switch; fakes for bank auth and CBS.
- **Related:** `docs/design/data-model.md` (entities), `docs/contracts/staff-api.md` (HTTP), ADR-0002 (sessions, jobs, audit).

## 1. Layout and dependency rule
| Location | Contents |
|---|---|
| `src/backend/domain/` | Domain dataclasses (enrolment aggregate, customer snapshot, user, plan, ...), state machine, `repositories.py` (the ports below as `typing.Protocol`s, query and page types, `VersionConflict`, `DuplicateKey`) |
| `src/backend/services/` | Use cases; depend only on `domain` ports and adapter ports, receive a `UnitOfWorkFactory` |
| `src/backend/persistence/memory/` | In-memory implementation + seed loader |
| `src/backend/persistence/sql/` | SQLAlchemy implementation (T-002); ORM models never leave this package |
| `src/backend/persistence/seed/synthetic_v1.json` | The synthetic fixture (section 5); excluded from production bundles (`release/allowlist.txt`) |
| `src/backend/bootstrap.py` | Composition root: reads `Settings`, builds the UoW factory and adapters, registers readiness checks. Only place that imports `persistence.memory`/`persistence.sql` or concrete adapters |

Services and routes never import a concrete repository or adapter; swapping `APP_DATA_BACKEND` changes nothing else (Decided requirement).

## 2. Repository ports (one per aggregate)
Repositories take and return domain objects (copies), never ORM rows. All `search`/`list` methods take an explicit `branch_codes: frozenset[str] | None` (None = all branches); scoping is decided by the service from the session, never by the repository.

| Port | Aggregate (tables) | Methods |
|---|---|---|
| `EnrolmentRepository` | `enrolment` + `enrolment_nominee`, `enrolment_status_history`, `cbs_posting`, `insurer_call`, `cancellation` | `get(id)`, `get_for_update(id)`, `get_by_reference(our_reference_no)`, `add(e)`, `save(e)` (whole aggregate; raises `VersionConflict` if `version` moved; bumps `version`), `next_reference_no()`, `search(EnrolmentQuery) -> Page[EnrolmentSummary]`, `count_by_status(branch_codes, created_since) -> dict`, `sum_gross_issued(branch_codes, since) -> Decimal`, `find_posting_by_request_ref(ref)` |
| `ApprovalRepository` | `approval` | `get(id)`, `add(a)`, `save(a)`, `pending_for(entity_type, entity_id, action=None)`, `search(ApprovalQuery) -> Page` (filters: status, action, branch_codes). `ATTENTION_RESOLVE` approvals carry the proposed target status and evidence ref; the memory store holds them as fields, the SQL backend needs two nullable `approval` columns (pending schema change, Q36) |
| `CustomerRepository` | `customer` + `customer_account` | `get(id)`, `get_by_cif(cif)`, `upsert_snapshot(customer, accounts) -> Customer` (refresh at each new sale), `get_account(customer_account_id)`, `find_account(customer_id, account_hash)` |
| `UserRepository` | `app_user`, `user_role`, `branch` | `get(id)`, `get_by_roll_no(roll_no)`, `upsert_from_bank(identity) -> User` (no role on first login), `roles_for(user_id)`, `get_branch(code)`, `upsert_branch(b)` |
| `SessionRepository` | `user_session`, `login_throttle`, login challenge (memory store only for now, Decided; SQL table is a pending schema change, Q36) | `create(s)`, `get_by_hash(h)`, `touch(h, now, idle_expires_at)`, `revoke(h, reason)`, `revoke_all_for_user(user_id, reason)`; `add_challenge(c)`, `consume_challenge(id, now) -> Challenge or None` (single use); `throttle_get(key)`, `throttle_save(t)` |
| `ReferenceRepository` | `insurer`, `insurer_product`, `insurer_plan`, `plan_rate`, `ref_code`, `insurer_code_map`, `pool_account`, `app_setting` | `list_plans(product_code, on_date)` (with rate in force), `get_plan(product_code, plan_code)`, `get_rate(rate_id)`, `codes(category=None)`, `map_code(insurer_id, category, our_code)`, `active_pool_account(product_id, on_date)`, `setting(key) -> str or None` |
| `AuditRepository` | `audit_event` | `append(event) -> AuditEvent` (assigns `audit_id`, `prev_hash`, `row_hash` under the chain lock), `verify_chain(from_id=None) -> bool`. No update or delete method exists |
| `JobRepository` | `job` | `enqueue(job) -> Job` (returns the existing job for a duplicate `dedupe_key`), `claim_due(now, limit, worker_id)` (SQL: `FOR UPDATE SKIP LOCKED`), `complete(id)`, `fail(id, error, run_after)`, `mark_dead(id, error)`, `list(status, entity_id=None)` |
| `IdempotencyRepository` | `idempotency_key` | `reserve(scope, key, request_hash, expires_at) -> Reserved or Existing(record)`, `complete(scope, key, resource_id, response_status)`, `release(scope, key)` (on failure before any external call), `purge_expired(now)` |
| `DocumentRepository` | `document` | `add(doc)`, `get(id)`, `latest(enrolment_id, kind)`, `list_meta(enrolment_id)` (no content) |

`Page[T]` = `items, page, page_size, total`. `EnrolmentQuery` = `branch_codes, statuses, created_from, created_to, text_prefix, created_by, attention_only, page, page_size, sort`.

## 3. Unit of work
```
with uow_factory() as uow:          # begins a transaction (memory: takes the store lock, works on copies)
    e = uow.enrolments.get_for_update(id)
    ... domain change ...
    uow.enrolments.save(e); uow.audit.append(ev)
    uow.commit()                    # leaving without commit = rollback
```
| Rule | Status |
|---|---|
| One UoW per step; it exposes every repository as an attribute (`uow.enrolments`, `uow.audit`, ...) | Proposed |
| **No external call inside a UoW.** Pattern per external step: UoW 1 persists the intent (e.g. `cbs_posting` `PENDING`, `insurer_call` started) and commits; the adapter call runs outside; UoW 2 records the result and the transition. Matches "persist intent -> call -> persist result" (architecture.md) and keeps the memory lock short | Proposed |
| Status change, history row and audit event are written in the same UoW | Proposed |
| `VersionConflict` maps to HTTP 409 `VERSION_CONFLICT` | Proposed |

**Memory implementation.** One process-wide `MemoryStore` (dicts keyed by id, plus indexes for reference no, CIF, roll no, session hash, dedupe key). A UoW takes a single `threading.RLock`, deep-copies the objects it reads into a working set, and on `commit` writes them back; rollback discards the set. That gives the same all-or-nothing semantics as a SQL transaction. Unique keys and the version check are enforced in `commit`. Data is lost on restart (by design). **Single process only:** start uvicorn with one worker; the in-process job worker drains `JobRepository` the same way as with SQL.

## 4. Configuration switches
| Variable | Values (default first) | Notes |
|---|---|---|
| `APP_DATA_BACKEND` | `sql`, `memory` | `memory` loads `synthetic_v1.json` at start |
| `APP_INSURER_ADAPTER` | `fake`, `usgic` | `usgic` = real UAT adapter (`docs/contracts/usgic-gpa.md`) |
| `APP_BANK_AUTH` | `fake`, `esb` | `esb` waits for keys and vectors (Q29) |
| `APP_CBS` | `fake` | Directory and posting together; a real value is added with Q27/Q33 |
| `APP_SESSION_SECRET` | secret, >= 32 bytes | CSRF HMAC (`staff-api.md`); required unless `ENV=dev`/`demo` with memory, where a random one is generated per start |
| `APP_ALLOWED_ORIGINS` | comma list | `Origin` check on unsafe methods |
| `APP_USGIC_*` | `BASE_URL`, `USER_NAME`, `PRODUCT_CODE`, intermediary ids, `CIPHER` (`unconfigured`), cipher key and IV settings, connect/read timeouts | Secrets only from the protected config file. No values in the repo |

**Safety rule (Decided, product owner 2026-10-18):** add `ENV=demo`. `production` stays `ENV != "dev"`, so demo keeps production hardening (no docs, strict headers). Then:
1. `APP_DATA_BACKEND=memory` or any `fake` adapter is allowed **only** when `ENV` is `dev` or `demo`; otherwise startup fails with `ConfigError`.
2. `APP_DATABASE_URL` is required when `APP_DATA_BACKEND=sql` and `ENV != dev` (today's rule, now conditional on the backend); it is ignored with `memory`.
3. Defaults (`sql`, and the fakes) therefore fail closed in UAT/prod until real adapters are configured.
4. Whenever `memory` or a fake is active, `Me.environment.synthetic_data = true` and startup logs a warning.

Example demo run: `ENV=demo APP_DATA_BACKEND=memory APP_INSURER_ADAPTER=fake APP_BANK_AUTH=fake APP_CBS=fake`. Exercising USGIC UAT from our network: the same with `APP_INSURER_ADAPTER=usgic`.

**USGIC `PayloadCipher` fails closed (Decided requirement).** While `APP_USGIC_CIPHER=unconfigured` (default) or the key settings are missing, `encrypt` and `decrypt` raise `CipherNotConfigured`; there is no plaintext fallback. The adapter catches it **before sending** and returns `TransientError(UNAVAILABLE)` (nothing reached the insurer, so a retry is safe); the readiness check `insurer_cipher` reports `fail`. The real algorithm is added once Q26 is answered and verified against the insurer's sample ciphertexts in UAT.

## 5. Synthetic seed fixture (`synthetic_v1.json`)
Every name, number and rate is invented. Timestamps are stored as offsets ("days ago") and resolved against the clock at load, so the dashboard looks current. Two sections: `cbs_world` (what the fake CBS directory and posting adapters know) and `app` (our own store). The loader also primes the fake insurer and fake CBS with the proposals and postings of seeded enrolments, so `RECHECK` on seeded `NEEDS_ATTENTION` items works.

**Branches:** `0101` Synthetic Main, `0102` Synthetic East, `0900` Synthetic Head Office.

**Users** (fake bank auth; one shared synthetic password documented in the seed, accepted only by the fake):
| Roll no | Branch | Roles | Purpose |
|---|---|---|---|
| `D1001` | 0101 | BRANCH_USER | Maker |
| `D1002` | 0101 | CHECKER | Checker for 0101 |
| `D1003` | 0102 | BRANCH_USER, CHECKER | Shows "cannot approve own sale" |
| `D1004` | 0900 | OPERATIONS | Needs-attention queue, all branches |
| `D1005` | 0900 | AUDITOR, REPORT_VIEWER | Read-only, all branches |
| `D1006` | 0900 | ADMIN | Admin screens (later) |
| `D1007` | 0102 | none | Signs in, sees "no access" |

**Plans** (USGIC GPA, codes A, B, C), each with one rate row flagged `synthetic: true`, note "SYNTHETIC - NOT AN INSURER RATE":
| Plan | Sum insured | Net | GST | Gross | Term days |
|---|---|---|---|---|---|
| A | 100000.00 | 100.00 | 18.00 | 118.00 | 365 |
| B | 200000.00 | 180.00 | 32.40 | 212.40 | 365 |
| C | 500000.00 | 400.00 | 72.00 | 472.00 | 365 |
The fake insurer returns these figures as "its" premium (except trigger `6003`); the application still never calculates premium.

**Reference codes:** small synthetic lists for GENDER, RELATION, OCCUPATION, STATE, CONSENT_METHOD (`SIGNED_FORM`, `BRANCH_DECLARATION`, placeholders, Q28), CANCEL_REASON. Settings: `maker_checker.enrolment = true`, `maker_checker.cancellation = true`. One pool account `509900000001` (synthetic).

**CBS customers** (account numbers are 12 digits starting `5099`; the last four digits select behaviour, section 6):
| CIF | Customer | Accounts (status) | Shows |
|---|---|---|---|
| `SYN0001` | Asha Demo | `509900011001` (ACTIVE) | Happy path |
| `SYN0002` | Ravi Sample | `509900021002` (ACTIVE), `509900021003` current (ACTIVE), `509900021004` (DORMANT, not selectable) | Multi-account choice |
| `SYN0003` | Meena Test | `509900031005` (CLOSED) | Inactive account only: no selectable account |
| `SYN0004` | Kiran Example | `509900047001` (ACTIVE) | Posting declined |
| `SYN0005` | Farah Placeholder | `509900057002` (ACTIVE) | Posting unknown, resolves to success |
| `SYN0006` | Arjun Mock | `509900067003` (ACTIVE) | Posting unknown, unresolved |
| `SYN0007` | Leela Fixture | `509900076001` (ACTIVE), `509900077004` (ACTIVE) | Insurer rejects; account frozen at posting |
| `SYN0008` | Vikram Synthetic | `509900086003` (ACTIVE), `509900086005` (ACTIVE) | Premium mismatch; issue fails |
| `SYN0009` | Nisha Sampleton | `509900096002` (ACTIVE), (no e-mail, no occupation in CBS) | Insurer unknown outcome; missing CBS fields keyed by maker |

**Enrolments (26), spread over the three branches and the last 30 days:**
| Status | n | Notes |
|---|---|---|
| DRAFT | 3 | One complete, one missing nominees, one by `D1003` |
| PENDING_CHECK | 3 | Two in 0101 (for `D1002`), one in 0102 made by `D1003` |
| REJECTED | 1 | Checker comment present |
| APPROVED | 2 | Ready for "Send to insurer" |
| PROPOSAL_CREATED | 2 | One normal, one with `matches_rate = false` |
| PAYMENT_PENDING | 1 | |
| PAYMENT_FAILED | 1 | CBS declined |
| PAID | 1 | Retry job queued |
| ISSUED | 6 | Synthetic COI PDFs (generated, watermarked "SYNTHETIC - NOT A REAL CERTIFICATE") |
| PROPOSAL_REJECTED | 1 | Insurer message present |
| PROPOSAL_CANCELLED | 1 | |
| NEEDS_ATTENTION | 2 | `POSTING_UNKNOWN`, `ISSUE_RETRIES_EXHAUSTED` |
| CANCELLATION_PENDING | 1 | Pending checker approval |
| CANCELLED | 1 | Refund posting `SUCCESS` |
References `GIP-SYN-000001` onward; certificates `SYN/GPA/000001` onward; proposals `SYNP000001` onward. Each seeded enrolment has a consistent status history, postings, insurer calls and audit chain.

## 6. Scripted fake behaviours (for demoing failure paths)
Selected by the **last four digits of the debit account** (CBS and insurer fakes both see it; the insurer receives `AccountNo` in `create_proposal`), by the lookup identifier, or by roll number.

| Trigger | Fake | Behaviour | Expected app result |
|---|---|---|---|
| Account ending `0000`, or unknown CIF | CBS directory | `NotFound` | 404 `CUSTOMER_NOT_FOUND`, nothing saved |
| Account `509999999901` / CIF `SYN9901` | CBS directory | Unavailable | 503 `CBS_UNAVAILABLE` "try again" |
| Account `509999999902` / CIF `SYN9902` | CBS directory | Slow beyond timeout | 503 `CBS_UNAVAILABLE` (no hang) |
| `...6001` | Insurer | `create_proposal` rejected (validation text) | `PROPOSAL_REJECTED`, message shown |
| `...6002` | Insurer | `create_proposal` unknown outcome; `get_proposal` shows it created | `PROPOSAL_CREATED` after read-back; one proposal |
| `...6003` | Insurer | Premium differs from the synthetic rate | `PROPOSAL_CREATED`, `matches_rate=false`, payment 409 `PREMIUM_MISMATCH` |
| `...6004` | Insurer | Transient error once, then success | Outcome `QUEUED_FOR_RETRY`, then `PROPOSAL_CREATED` via job |
| `...6005` | Insurer | `issue_policy` transient error every time | `PAID` + retries, then `NEEDS_ATTENTION` (`ISSUE_RETRIES_EXHAUSTED`) |
| `...6006` | Insurer | `issue_policy` unknown; `get_proposal` shows issued | `ISSUED` after read-back |
| `...7001` | CBS posting | `FAILED` (declined) | `PAYMENT_FAILED`; retry needs fresh consent |
| `...7002` | CBS posting | `UNKNOWN`; `get_posting_status` = `SUCCESS` | `PAID` then `ISSUED`; one posting |
| `...7003` | CBS posting | `UNKNOWN`; status read also unclear | `NEEDS_ATTENTION` (`POSTING_UNKNOWN`); no second posting |
| `...7004` | CBS directory (`get_account` re-read) | Account now `FROZEN` | 409 `ACCOUNT_NOT_ELIGIBLE`, no posting |
| `...8001` | Insurer | `cancel_certificate` unknown outcome | `NEEDS_ATTENTION` (`CANCEL_UNKNOWN`) |
| Roll `D9001` | Bank auth | OTP required; OTP `123456` valid, anything else invalid | OTP step, then signed in as a BRANCH_USER of 0101 |
| Roll `D9002` | Bank auth | `LOCKED` | Generic 401 `LOGIN_FAILED` |
| Roll `D9003` | Bank auth | Unavailable | 503 `AUTH_UNAVAILABLE` |
| Wrong password, any roll | Bank auth | `FAILED` | Generic 401 `LOGIN_FAILED` |
All other accounts: success on every call. Fakes add a small configurable delay (default 300 ms) so loading states are visible.

## Open questions
Q26 (cipher, cancel), Q28 (consent codes), Q29 (bank auth keys), Q30 (premium mismatch owner), Q32 (roles), Q33 (CBS fields, selectable statuses), Q36 (open part only: SQL tables/columns for login challenges and `ATTENTION_RESOLVE` approvals are pending schema changes; `NEEDS_ATTENTION -> CANCELLED` is not in the spec, left unchanged, so `CANCEL_UNKNOWN` items stay open). Decided 2026-10-18: CSRF secret, `ENV=demo` rule, two-person operations `CONFIRM`.
