"""USGIC Group Personal Accident adapter for the UAT gateway (docs/contracts/usgic-gpa.md).

* Token call first (``GenerateToken``); the token id goes in a header, the JWT in
  ``Authorization``. Both are cached in memory, refreshed shortly before expiry and once on an
  authentication failure.
* Bodies are wrapped as ``{"Value": "<json>"}``, encrypted by the ``PayloadCipher`` and sent as
  ``{"Data": "<ciphertext>"}``; replies are ``{"response": "<ciphertext>"}``. The cipher fails
  closed: if it raises, nothing is sent and the outcome is ``TransientError(UNAVAILABLE)``.
* Request and reply field names follow the contract; names the contract leaves open are matched
  from a short candidate list (to confirm in UAT, Q26).
* Logs carry operation, our reference, outcome and duration only: never personal data, tokens,
  keys or payloads.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from backend.adapters.insurer.base import (
    CancellationResult,
    Certificate,
    ErrorCategory,
    IssueRequest,
    Outcome,
    PolicyIssued,
    ProposalCreated,
    ProposalRecord,
    ProposalRequest,
    Rejected,
    Success,
    TransientError,
    UnknownOutcome,
)
from backend.adapters.insurer.usgic.cipher import CipherError, CipherNotConfigured, PayloadCipher
from backend.adapters.insurer.usgic.parsing import (
    ReplyFormatError,
    classify_message,
    clean_text,
    format_request_date,
    is_success_status,
    parse_amount,
    parse_reply_date,
)

logger = logging.getLogger("backend.adapters.insurer.usgic")

INSURER_CODE = "USGIC"
# Our code -> insurer value lookup: (category, our_code) -> insurer value or None.
CodeMapper = Callable[[str, str], str | None]

# Reply field candidates (case-insensitive). The contract fixes some names; others are open (Q26).
_PROPOSAL_NO = ("ReferenceNo", "Reference_No", "ProposalNumber", "ProposalNo", "Proposal_No")
_NET = ("NetPremium", "Net_Premium")
_GST = ("GSTAmount", "ServiceTax", "GST_Amount")
_GROSS = ("GrossPremium", "Gross_Premium", "TotalPremium")
_STATUS = ("Status",)
_ERROR = ("ErrorDescription", "Error_Description", "ErrorMessage", "Message")
_CERT_NO = ("Policy_No", "PolicyNo", "Certificate_Id", "CertificateNo")
_START = ("Policy_Start_Date", "PolicyStartDate", "StartDate")
_END = ("Policy_End_Date", "PolicyEndDate", "EndDate")
_PAYMENT_STATUS = ("Payment_Status", "PaymentStatus")
_REFUND = ("RefundAmount", "Refund_Amount")
_REFUND_DATE = ("RefundDate", "Refund_Date")
_PDF = ("PolicyDocument", "Document", "FileData", "Base64", "PdfData", "File")
_TOKEN_ID = ("TokenId", "Token_Id", "tokenId")
_JWT = ("JwtToken", "Jwt", "Token", "AccessToken", "access_token")


@dataclass(frozen=True)
class UsgicConfig:
    base_url: str
    user_name: str
    product_code: str
    password: str | None = None
    intermediary_code: str | None = None
    intermediary_branch_code: str | None = None
    token_header: str = "TokenId"  # noqa: S105 - a header name, not a secret
    refresh_margin_seconds: int = 300
    default_token_ttl_seconds: int = 3000
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 30.0
    # ABHI Azure APIM subscription key; sent as Ocp-Apim-Subscription-Key header.
    apim_subscription_key: str | None = None  # noqa: S105 - a config field name, not a secret


class _AuthFailure(Exception):
    pass


class _Transient(Exception):
    def __init__(self, category: ErrorCategory) -> None:
        super().__init__(category.value)
        self.category = category


class _Unknown(Exception):
    def __init__(self, category: ErrorCategory = ErrorCategory.UNKNOWN) -> None:
        super().__init__(category.value)
        self.category = category


@dataclass
class _Token:
    token_id: str
    jwt: str
    expires_at: datetime


def _pick(data: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    lowered = {k.lower(): v for k, v in data.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _jwt_expiry(jwt: str) -> datetime | None:
    """Read the ``exp`` claim (no verification: we are the client, the insurer signs it)."""
    parts = jwt.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        exp = claims.get("exp")
    except (ValueError, binascii.Error, AttributeError):
        return None
    if isinstance(exp, int | float) and not isinstance(exp, bool):
        return datetime.fromtimestamp(int(exp), UTC)
    return None


class UsgicInsurer:
    insurer_code = INSURER_CODE

    def __init__(
        self,
        config: UsgicConfig,
        cipher: PayloadCipher,
        code_mapper: CodeMapper,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._cipher = cipher
        self._map = code_mapper
        self._clock = clock or (lambda: datetime.now(UTC))
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(
                config.read_timeout_seconds,
                connect=config.connect_timeout_seconds,
                read=config.read_timeout_seconds,
                write=config.read_timeout_seconds,
                pool=config.connect_timeout_seconds,
            ),
            transport=transport,
            follow_redirects=False,
        )
        self._token: _Token | None = None
        self._token_lock = threading.Lock()

    @property
    def timeout(self) -> httpx.Timeout:
        return self._client.timeout

    # ------------------------------------------------------------------ transport
    def _encode(self, body: Mapping[str, Any]) -> dict[str, str]:
        wrapped = json.dumps({"Value": json.dumps(body, default=str)})
        return {"Data": self._cipher.encrypt(wrapped)}  # raises CipherNotConfigured

    def _decode(self, response: httpx.Response) -> dict[str, Any]:
        try:
            outer = response.json()
            ciphertext = outer["response"] if isinstance(outer, dict) else None
            if not isinstance(ciphertext, str):
                raise _Unknown(ErrorCategory.UNKNOWN)
            plain = self._cipher.decrypt(ciphertext)
            data = json.loads(plain, parse_float=Decimal)
            if isinstance(data, dict) and set(data) == {"Value"} and isinstance(data["Value"], str):
                data = json.loads(data["Value"], parse_float=Decimal)
            if isinstance(data, list) and data and isinstance(data[0], dict):
                data = data[0]
        except (ValueError, KeyError, TypeError, CipherError, CipherNotConfigured) as exc:
            raise _Unknown(ErrorCategory.UNKNOWN) from exc
        if not isinstance(data, dict):
            raise _Unknown(ErrorCategory.UNKNOWN)
        return data

    def _post(
        self, method: str, body: Mapping[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        payload = self._encode(body)  # before any network activity
        try:
            response = self._client.post(method, json=payload, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise _Transient(ErrorCategory.UNAVAILABLE) from exc
        except httpx.TimeoutException as exc:
            raise _Unknown(ErrorCategory.TIMEOUT) from exc
        except httpx.TransportError as exc:  # dropped after send: may have taken effect
            raise _Unknown(ErrorCategory.UNKNOWN) from exc
        if response.status_code in (401, 403):
            raise _AuthFailure
        if response.status_code == 503:
            raise _Transient(ErrorCategory.UNAVAILABLE)
        if response.status_code >= 500:
            raise _Unknown(ErrorCategory.UNKNOWN)
        if response.status_code >= 400:
            data: dict[str, Any] = {}
            try:
                data = self._decode(response)
            except _Unknown:
                data = {}
            message = clean_text(_pick(data, _ERROR))
            category = (
                ErrorCategory.NOT_FOUND
                if response.status_code == 404
                else (classify_message(message) if message else ErrorCategory.VALIDATION)
            )
            if category == ErrorCategory.AUTH:
                raise _AuthFailure
            raise _RejectedReply(category, message)
        data = self._decode(response)
        message = clean_text(_pick(data, _ERROR))
        status = _pick(data, _STATUS)
        if status is not None and not is_success_status(status):
            category = classify_message(message)
            if category == ErrorCategory.AUTH:
                raise _AuthFailure
            raise _RejectedReply(category, message)
        return data

    def _fetch_token(self) -> _Token:
        body = {
            "UserName": self._config.user_name,
            "ProductCode": self._config.product_code,
            "IntermediaryCode": self._config.intermediary_code,
            "IntermediaryBranchCode": self._config.intermediary_branch_code,
        }
        if self._config.password is not None:
            body["Password"] = self._config.password
        try:
            data = self._post("GenerateToken", body, {})
        except _AuthFailure as exc:
            raise _Transient(ErrorCategory.AUTH) from exc
        except _RejectedReply as exc:
            raise _Transient(ErrorCategory.AUTH) from exc
        except _Unknown as exc:  # nothing to undo on a token call: safe to retry later
            raise _Transient(ErrorCategory.UNAVAILABLE) from exc
        token_id, jwt = clean_text(_pick(data, _TOKEN_ID)), clean_text(_pick(data, _JWT))
        if not token_id or not jwt:
            raise _Transient(ErrorCategory.AUTH)
        now = self._clock()
        expires = _jwt_expiry(jwt) or now + timedelta(
            seconds=self._config.default_token_ttl_seconds
        )
        return _Token(token_id, jwt, expires)

    def _headers(self, force_refresh: bool) -> dict[str, str]:
        with self._token_lock:
            margin = timedelta(seconds=self._config.refresh_margin_seconds)
            token = self._token
            if force_refresh or token is None or self._clock() >= token.expires_at - margin:
                token = self._fetch_token()
                self._token = token
        headers = {
            "Authorization": f"Bearer {token.jwt}",
            self._config.token_header: token.token_id,
        }
        # ABHI Azure APIM authentication: subscription key in every request.
        if self._config.apim_subscription_key:
            headers["Ocp-Apim-Subscription-Key"] = self._config.apim_subscription_key
        return headers

    def _call(self, method: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """One operation, refreshing the token once on an authentication failure."""
        try:
            return self._post(method, body, self._headers(False))
        except _AuthFailure:
            pass
        try:
            return self._post(method, body, self._headers(True))
        except _AuthFailure as exc:
            raise _Transient(ErrorCategory.AUTH) from exc

    def _run[T](self, operation: str, reference: str, action: Callable[[], T]) -> Outcome[T]:
        begin = time.perf_counter()
        outcome: Outcome[T]
        try:
            outcome = Success(action())
        except CipherNotConfigured:
            outcome = TransientError(ErrorCategory.UNAVAILABLE)
        except _Transient as exc:
            outcome = TransientError(exc.category)
        except _RejectedReply as exc:
            outcome = Rejected(exc.category, exc.message)
        except (_Unknown, ReplyFormatError) as exc:
            category = exc.category if isinstance(exc, _Unknown) else ErrorCategory.UNKNOWN
            outcome = UnknownOutcome(category)
        logger.info(
            "insurer call",
            extra={
                "insurer": INSURER_CODE,
                "operation": operation,
                "our_reference": reference,
                "outcome": type(outcome).__name__,
                "duration_ms": round((time.perf_counter() - begin) * 1000, 1),
            },
        )
        return outcome

    # ------------------------------------------------------------------ mapping
    def _code(self, category: str, our_code: str | None) -> str | None:
        if our_code is None:
            return None
        value = self._map(category, our_code)
        if value is None:
            raise _RejectedReply(ErrorCategory.VALIDATION, f"No insurer mapping for {category}")
        return value

    def proposal_body(self, r: ProposalRequest) -> dict[str, Any]:
        nominees = [
            {
                "NomineeName": n.name,
                "NomineeDOB": format_request_date(n.date_of_birth) if n.date_of_birth else None,
                "NomineeAge": n.age,
                "Nominee_Relation": self._code("RELATION", n.relation_code),
                "NomineeMobile": n.mobile,
                "NomineeEmail": n.email,
                "NomineeGender": self._code("GENDER", n.gender_code),
                "NomineePresentAddress": n.present_address,
                "NomineePermanentAddress": n.permanent_address,
                "NomineeBankAccountNo": n.bank_account_no,
                "NomineeIFSC": n.ifsc,
                "NomineeBankName": n.bank_name,
                "NomineeAccountHolderName": n.account_holder_name,
                "NomineePerPayAmt": str(n.share_percent),
                "AppointeeName": n.appointee_name,
                "AppointeeRelation": self._code("RELATION", n.appointee_relation_code),
                "AppointeeDOB": format_request_date(n.appointee_dob) if n.appointee_dob else None,
                "AppointeeAge": n.appointee_age,
                "AppointeeGender": self._code("GENDER", n.appointee_gender_code),
            }
            for n in r.nominees
        ]
        return {
            "IOBReference_No": r.our_reference_no,
            "PolicyNo": "",
            "ProductCode": "",
            "BranchCode": self._code("BRANCH", r.branch_code),
            "BankCustomerId": r.bank_customer_id,
            "FirstName": r.first_name.upper(),
            "MiddleName": r.middle_name.upper() if r.middle_name else None,
            "LastName": r.last_name.upper(),
            "Gender": self._code("GENDER", r.gender_code),
            "DateOfBirth": format_request_date(r.date_of_birth),
            "Email": r.email,
            "Mobile": "".join(ch for ch in r.mobile if ch.isdigit()),
            "Address1": r.address1,
            "Address2": r.address2,
            "City": r.city,
            "State": self._code("STATE", r.state_code),
            "PinCode": r.pincode,
            "Occupation": self._code("OCCUPATION", r.occupation_code),
            "OtherOccupation": r.other_occupation,
            "AnyDisability": "Y" if r.any_disability else "N",
            "DisabilityDescription": r.disability_description,
            "NameAndAddressOfGuardian": r.guardian_name_address,
            "Plan": r.plan_code,
            "AccountNo": r.account_no,
            "NomineeDetails": nominees,
        }

    # ------------------------------------------------------------------ operations
    def create_proposal(
        self, request: ProposalRequest, *, correlation_id: str | None
    ) -> Outcome[ProposalCreated]:
        def action() -> ProposalCreated:
            data = self._call("InsertInsuredDetailsGPA", self.proposal_body(request))
            proposal_no = clean_text(_pick(data, _PROPOSAL_NO))
            net, gst = parse_amount(_pick(data, _NET)), parse_amount(_pick(data, _GST))
            gross = parse_amount(_pick(data, _GROSS))
            if not proposal_no or net is None or gst is None or gross is None:
                raise ReplyFormatError("proposal reply incomplete")
            return ProposalCreated(proposal_no, net, gst, gross, clean_text(_pick(data, _STATUS)))

        return self._run("create_proposal", request.our_reference_no, action)

    def issue_policy(
        self, request: IssueRequest, *, correlation_id: str | None
    ) -> Outcome[PolicyIssued]:
        def action() -> PolicyIssued:
            body = {
                "ProposalNumber": request.proposal_no,
                "BankCustomerId": request.bank_customer_id,
                "Payment_Status": request.payment_status,
                "TransactionNumber": request.transaction_no,
                "TransactionDate": (
                    format_request_date(request.transaction_date)
                    if request.transaction_date
                    else None
                ),
                "TokenId": None,
            }
            data = self._call("GeneratePolicy", body)
            cert = clean_text(_pick(data, _CERT_NO))
            start, end = parse_reply_date(_pick(data, _START)), parse_reply_date(_pick(data, _END))
            if not cert or start is None or end is None:
                raise ReplyFormatError("policy reply incomplete")
            return PolicyIssued(cert, start, end)

        return self._run("issue_policy", request.our_reference_no, action)

    def fetch_certificate(
        self, certificate_no: str, proposal_no: str | None, *, correlation_id: str | None
    ) -> Outcome[Certificate]:
        def action() -> Certificate:
            body = {
                "ProposalNumber": proposal_no,
                "PolicyNo": certificate_no,
                "ProposalType": "COI",
            }
            data = self._call("FetchPolicy", body)
            candidates = [_pick(data, _PDF), *data.values()]
            for value in candidates:
                if isinstance(value, str) and len(value) > 16:
                    try:
                        content = base64.b64decode(value, validate=True)
                    except (binascii.Error, ValueError):
                        continue
                    if content.startswith(b"%PDF"):
                        return Certificate(content)
            raise ReplyFormatError("no PDF in reply")

        return self._run("fetch_certificate", certificate_no, action)

    def get_proposal(
        self, *, proposal_no: str | None, our_reference: str, correlation_id: str | None
    ) -> Outcome[ProposalRecord]:
        if not proposal_no:
            # FetchPolicyDataGPA reads by proposal number only; a lookup by our reference is
            # not documented (Q26), so the state stays unknown.
            return UnknownOutcome(ErrorCategory.UNKNOWN)

        def action() -> ProposalRecord:
            data = self._call("FetchPolicyDataGPA", {"ProposalNumber": proposal_no})
            status = clean_text(_pick(data, _STATUS))
            return ProposalRecord(
                proposal_no=clean_text(_pick(data, _PROPOSAL_NO)) or proposal_no,
                status=status,
                payment_status=clean_text(_pick(data, _PAYMENT_STATUS)),
                certificate_no=clean_text(_pick(data, _CERT_NO)),
                risk_start_date=parse_reply_date(_pick(data, _START)),
                risk_end_date=parse_reply_date(_pick(data, _END)),
                net_premium=parse_amount(_pick(data, _NET)),
                gst_amount=parse_amount(_pick(data, _GST)),
                gross_premium=parse_amount(_pick(data, _GROSS)),
                cancelled=bool(status and "CANCEL" in status.upper()),
            )

        return self._run("get_proposal", our_reference, action)

    def cancel_certificate(
        self, certificate_no: str, *, our_reference: str, correlation_id: str | None
    ) -> Outcome[CancellationResult]:
        def action() -> CancellationResult:
            data = self._call("CertificateCancellationGPA", {"Certificate_Id": certificate_no})
            return CancellationResult(
                parse_amount(_pick(data, _REFUND)), parse_reply_date(_pick(data, _REFUND_DATE))
            )

        return self._run("cancel_certificate", our_reference, action)

    def cancel_proposal(
        self, proposal_no: str, *, our_reference: str, correlation_id: str | None
    ) -> Outcome[bool]:
        def action() -> bool:
            # Documented under the certificate-cancel path; probably a document error (Q26).
            self._call("CertificateCancellationGPA", {"ProposalNumber": proposal_no})
            return True

        return self._run("cancel_proposal", our_reference, action)

    def close(self) -> None:
        self._client.close()


class _RejectedReply(Exception):
    def __init__(self, category: ErrorCategory, message: str | None) -> None:
        super().__init__(category.value)
        self.category = category
        self.message = message[:300] if message else None
