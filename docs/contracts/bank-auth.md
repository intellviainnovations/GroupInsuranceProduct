# Contract: bank authentication

- **Status:** Proposed (architect draft, 2026-10-18). Based on the bank's AD/CHRISS authentication API release notes (a bank document, **not stored in this repo**). No URLs, client credentials, keys or real identifiers are recorded here.
- **Purpose:** staff sign in with the bank's own credentials. Our application never owns passwords. Other banks may later plug in a different provider (D-020).
- **Location in code:** `src/backend/adapters/bank_auth/` with `base.py` (the port), `esb/` (this bank), `fake/` (development and tests).

## Port
```
authenticate(branch_code, user_id, password, request_id) -> AuthResult
verify_otp(challenge_ref, otp, request_id)                -> AuthResult
logout(bank_session_ref)                                  -> None   (only if the bank offers it, Q29)
```
`AuthResult` has: `status` (`SUCCESS`, `FAILED`, `OTP_REQUIRED`, `LOCKED`, `UNAVAILABLE`), an `identity` on success (`user_id`, `email`, `designation`, `branch_code`), a `challenge_ref` when an OTP is required, and a `bank_session_ref` (stored encrypted in `user_session`).

## Our session flow
1. The browser posts branch code, roll number and password over TLS to our backend. The backend, not the browser, calls the bank. The browser never contacts the bank.
2. On `SUCCESS` (and OTP if required) we upsert `app_user` by roll number, refresh branch and designation from the bank's reply, create a `user_session`, and set an opaque cookie (HttpOnly, Secure, SameSite). The branch used by the application always comes from the bank's reply, never from the request.
3. Roles come from our own `user_role` table, not from the designation text (Q32). A user with no role can sign in but sees nothing.
4. Failed attempts return one generic message. Throttling uses `login_throttle`. Every outcome writes an `audit_event` without the password.

## Mapping for the bank's ESB provider
| Our concept | Bank API (as documented) |
|---|---|
| Application token | An OAuth2 client-credentials token for a scope named for AD authentication; client id and secret from configuration; cache until shortly before expiry (lifetime not documented, Q29) |
| `authenticate` | One POST with branch code, user id, password, channel `ESB`, authentication type `AD`, an OTP flag, a biometric flag and a unique `requestId` we generate per attempt |
| OTP step | A second POST with `RequestId`, `SessionId`, and the OTP |
| Reply fields | Statuses for AD, CHRISS and biometric checks, user id, email, employee designation, branch code, `SessionId`, `RequestId` |
| `status` mapping | Success only when the overall status and the AD status both say success; anything else is `FAILED`. The biometric status in the sample shows failure alongside success: whether it must pass is **not documented** (Q29) |

### Payload protection
Request and reply bodies are `{"Req": {"enc", "HMAC"}}` and `{"Res": {"enc", "HMAC"}}`. The document specifies AES-256-CBC with a random 16-byte IV prepended to the ciphertext, and an HMAC-SHA256 over the encrypted data. Rules for our implementation:
- Verify the HMAC with a constant-time comparison **before** decrypting; reject on mismatch.
- A fresh random IV per message.
- The key is supplied by the bank out of band (not yet received, Q29). Whether the encryption key and the HMAC key are separate is not stated (Q29).
- Use the `cryptography` library only. Keys from configuration, never logged, never in the repo.

## Security requirements (clearance matrix rows C-01 to C-09, C-27, C-32)
- The password exists only in memory for the duration of the call; it is never written to logs, audit events, exceptions or the database.
- Generic error messages; no hint whether the user, branch or password was wrong.
- Session id: 256-bit random, stored only as a hash, rotated at login, revoked at logout, with idle and absolute timeouts (values from the bank's policy, Q29).
- If the bank's MFA covers OTP and biometrics, the matching controls may become "NA, delegated to the bank", which needs the bank's written acceptance (Q9, Q29).
- Captcha, if the bank wants it on our login page, is ours to build (C-05, Q29).

## Fake provider
`fake/` accepts a configured list of synthetic users (roll numbers, branches, designations) and can return every status: success, wrong password, OTP required then valid or invalid, locked, bank unavailable, slow. Used by tests and by local development outside the bank network (D-008).

## Open points (Q29)
Key and sample test vectors; OAuth token lifetime; bank session timeout and logout call; the error code for a wrong password (the documented list covers accounts and OTP, not credentials); lockout policy; whether the biometric flag can be off for a browser client; a role or designation list; a UAT account; two different success codes appear in the document.
