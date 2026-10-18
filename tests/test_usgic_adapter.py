"""Builder's unit tests for the USGIC adapter against httpx.MockTransport. Synthetic replies only.

The identity cipher below exists only in this test: the real cipher is unknown (Q26) and the
shipped default fails closed.
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from backend.adapters.insurer.base import (
    ErrorCategory,
    IssueRequest,
    ProposalNominee,
    ProposalRequest,
    Rejected,
    Success,
    TransientError,
    UnknownOutcome,
)
from backend.adapters.insurer.usgic.adapter import UsgicConfig, UsgicInsurer
from backend.adapters.insurer.usgic.cipher import UnconfiguredCipher
from backend.adapters.insurer.usgic.parsing import (
    ReplyFormatError,
    classify_message,
    parse_amount,
    parse_reply_date,
)

CODES = {
    ("GENDER", "F"): "Female",
    ("STATE", "TN"): "TAMIL NADU",
    ("OCCUPATION", "SALARIED"): "Salaried",
    ("RELATION", "SPOUSE"): "Spouse",
    ("BRANCH", "0101"): "900101",
}
ACCOUNT = "509900011001"
NAME = "Asha"


class IdentityCipher:
    configured = True

    def encrypt(self, plaintext: str) -> str:
        return base64.b64encode(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return base64.b64decode(ciphertext).decode()


def jwt(exp: datetime) -> str:
    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'HS256'})}.{part({'exp': int(exp.timestamp())})}.c2ln"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class Insurer:
    """Scripted mock gateway; ``replies`` maps method -> callable returning (status, body)."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.requests: list[tuple[str, dict[str, Any], httpx.Headers]] = []
        self.tokens = 0
        self.replies: dict[str, Callable[[dict[str, Any]], tuple[int, Any]]] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        outer = json.loads(request.content)
        inner = json.loads(json.loads(base64.b64decode(outer["Data"]).decode())["Value"])
        self.requests.append((method, inner, request.headers))
        if method == "GenerateToken":
            self.tokens += 1
            reply: Any = {
                "Status": "SUCCESS",
                "TokenId": f"tid-{self.tokens}",
                "JwtToken": jwt(self.clock.now + timedelta(hours=1)),
            }
            status = 200
        else:
            status, reply = self.replies[method](inner)
        if isinstance(reply, str):
            return httpx.Response(status, json={"response": reply})
        text = base64.b64encode(json.dumps(reply).encode()).decode()
        return httpx.Response(status, json={"response": text})


def build(cipher: Any = None) -> tuple[UsgicInsurer, Insurer, Clock]:
    clock = Clock()
    fake = Insurer(clock)
    adapter = UsgicInsurer(
        UsgicConfig(
            base_url="https://usgic-uat.invalid/api",
            user_name="SYNUSER",
            product_code="SYNGPA",
            intermediary_code="SYN-INT",
            connect_timeout_seconds=3.0,
            read_timeout_seconds=20.0,
        ),
        cipher or IdentityCipher(),
        lambda category, code: CODES.get((category, code)),
        transport=httpx.MockTransport(fake.handler),
        clock=clock,
    )
    return adapter, fake, clock


def proposal_request() -> ProposalRequest:
    return ProposalRequest(
        our_reference_no="GIP-SYN-000099",
        branch_code="0101",
        bank_customer_id="SYN0001",
        plan_code="A",
        account_no=ACCOUNT,
        first_name=NAME,
        last_name="Demo",
        gender_code="F",
        date_of_birth=date(1985, 4, 12),
        mobile="90000-00001",
        address1="1 Synthetic Street",
        city="Demo City",
        state_code="TN",
        pincode="600001",
        occupation_code="SALARIED",
        any_disability=False,
        nominees=[
            ProposalNominee(
                name="Synthetic Spouse",
                relation_code="SPOUSE",
                share_percent=Decimal("100"),
                date_of_birth=date(1984, 1, 2),
            )
        ],
    )


def created_reply(_: dict[str, Any]) -> tuple[int, Any]:
    return 200, {
        "Status": "SUCCESS",
        "ReferenceNo": "SYNP900001",
        "NetPremium": "100.00",
        "GSTAmount": 18.0,
        "GrossPremium": "118.00",
    }


def test_create_proposal_maps_fields_and_parses_decimal_premium() -> None:
    adapter, fake, _ = build()
    fake.replies["InsertInsuredDetailsGPA"] = created_reply
    outcome = adapter.create_proposal(proposal_request(), correlation_id="corr-0001")
    assert isinstance(outcome, Success)
    assert outcome.data.proposal_no == "SYNP900001"
    assert outcome.data.gst_amount == Decimal("18.0")
    assert all(
        isinstance(v, Decimal) for v in (outcome.data.net_premium, outcome.data.gross_premium)
    )
    method, body, headers = fake.requests[-1]
    assert method == "InsertInsuredDetailsGPA"
    assert body["IOBReference_No"] == "GIP-SYN-000099"
    assert body["Gender"] == "Female"
    assert body["State"] == "TAMIL NADU"
    assert body["BranchCode"] == "900101"
    assert body["Occupation"] == "Salaried"
    assert body["DateOfBirth"] == "12/04/1985"
    assert body["Mobile"] == "9000000001"
    assert body["FirstName"] == "ASHA"
    assert body["AnyDisability"] == "N"
    assert body["NomineeDetails"][0]["Nominee_Relation"] == "Spouse"
    assert body["NomineeDetails"][0]["NomineeDOB"] == "02/01/1984"
    assert headers["authorization"].startswith("Bearer ")
    assert headers["tokenid"] == "tid-1"


def test_token_is_cached_and_refreshed_before_expiry() -> None:
    adapter, fake, clock = build()
    fake.replies["InsertInsuredDetailsGPA"] = created_reply
    adapter.create_proposal(proposal_request(), correlation_id=None)
    adapter.create_proposal(proposal_request(), correlation_id=None)
    assert fake.tokens == 1
    clock.now += timedelta(minutes=56)  # inside the 5-minute refresh margin
    adapter.create_proposal(proposal_request(), correlation_id=None)
    assert fake.tokens == 2


def test_auth_failure_forces_one_refresh_then_transient() -> None:
    adapter, fake, _ = build()
    calls = {"n": 0}

    def unauthorised_once(_: dict[str, Any]) -> tuple[int, Any]:
        calls["n"] += 1
        return (401, {}) if calls["n"] == 1 else created_reply({})

    fake.replies["InsertInsuredDetailsGPA"] = unauthorised_once
    assert isinstance(adapter.create_proposal(proposal_request(), correlation_id=None), Success)
    assert fake.tokens == 2
    fake.replies["InsertInsuredDetailsGPA"] = lambda _: (401, {})
    outcome = adapter.create_proposal(proposal_request(), correlation_id=None)
    assert outcome == TransientError(ErrorCategory.AUTH)


def test_unconfigured_cipher_fails_closed_before_sending() -> None:
    sent: list[httpx.Request] = []
    adapter = UsgicInsurer(
        UsgicConfig(base_url="https://usgic-uat.invalid", user_name="U", product_code="P"),
        UnconfiguredCipher(),
        lambda c, v: CODES.get((c, v)),
        transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200)),
    )
    outcome = adapter.create_proposal(proposal_request(), correlation_id=None)
    assert outcome == TransientError(ErrorCategory.UNAVAILABLE)
    assert sent == []


def test_outcome_classifier() -> None:
    adapter, fake, _ = build()
    fake.replies["InsertInsuredDetailsGPA"] = lambda _: (
        200,
        {"Status": "FAILURE", "ErrorDescription": "Nominee DOB is invalid"},
    )
    rejected = adapter.create_proposal(proposal_request(), correlation_id=None)
    assert rejected == Rejected(ErrorCategory.VALIDATION, "Nominee DOB is invalid")
    fake.replies["InsertInsuredDetailsGPA"] = lambda _: (200, "not-base64-or-json")
    assert isinstance(
        adapter.create_proposal(proposal_request(), correlation_id=None), UnknownOutcome
    )
    fake.replies["InsertInsuredDetailsGPA"] = lambda _: (502, {})
    assert isinstance(
        adapter.create_proposal(proposal_request(), correlation_id=None), UnknownOutcome
    )
    fake.replies["InsertInsuredDetailsGPA"] = lambda _: (503, {})
    assert adapter.create_proposal(proposal_request(), correlation_id=None) == TransientError(
        ErrorCategory.UNAVAILABLE
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ConnectError("x"), TransientError),
        (httpx.ReadTimeout("x"), UnknownOutcome),
        (httpx.RemoteProtocolError("x"), UnknownOutcome),
    ],
)
def test_transport_errors(error: Exception, expected: type) -> None:
    adapter, fake, _ = build()
    original = fake.handler

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("GenerateToken"):
            return original(request)
        raise error

    adapter._client._transport = httpx.MockTransport(handler)  # type: ignore[attr-defined]
    assert isinstance(adapter.create_proposal(proposal_request(), correlation_id=None), expected)


def test_issue_policy_parses_reply_dates() -> None:
    adapter, fake, _ = build()
    fake.replies["GeneratePolicy"] = lambda body: (
        200,
        {
            "Status": "SUCCESS",
            "Policy_No": "SYN/GPA/900001",
            "Policy_Start_Date": "08/01/2026",
            "Policy_End_Date": "07-01-2027 23:59:59",
        },
    )
    outcome = adapter.issue_policy(
        IssueRequest(
            "GIP-SYN-000099", "SYNP900001", "SYN0001", "SUCCESS", "SYNTXN000001", date(2026, 1, 8)
        ),
        correlation_id=None,
    )
    assert isinstance(outcome, Success)
    assert outcome.data.risk_start_date == date(2026, 1, 8)
    assert outcome.data.risk_end_date == date(2027, 1, 7)
    assert fake.requests[-1][1]["TransactionDate"] == "08/01/2026"


def test_timeouts_come_from_configuration() -> None:
    adapter, _, _ = build()
    assert adapter.timeout.connect == 3.0
    assert adapter.timeout.read == 20.0


def test_get_proposal_without_number_is_unknown() -> None:
    adapter, fake, _ = build()
    outcome = adapter.get_proposal(proposal_no=None, our_reference="GIP-SYN-1", correlation_id=None)
    assert isinstance(outcome, UnknownOutcome)
    assert fake.requests == []


def test_no_personal_data_or_tokens_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    adapter, fake, _ = build()
    fake.replies["InsertInsuredDetailsGPA"] = created_reply
    with caplog.at_level(logging.DEBUG):
        adapter.create_proposal(proposal_request(), correlation_id=None)
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for leaked in (ACCOUNT, NAME.upper(), "tid-1", "Bearer", "SYN0001"):
        assert leaked not in text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-01-08T00:00:00", date(2026, 1, 8)),
        ("2026-01-08T10:30:00.000Z", date(2026, 1, 8)),
        ("08-01-2026 10:30:00", date(2026, 1, 8)),
        ("08/01/2026", date(2026, 1, 8)),
        ("null", None),
        ("", None),
        (None, None),
    ],
)
def test_reply_date_shapes(value: Any, expected: date | None) -> None:
    assert parse_reply_date(value) == expected


@pytest.mark.parametrize("value", ["2026/01/08", "8 Jan 2026", "31/02/2026", 20260108])
def test_reply_date_rejects_other_shapes(value: Any) -> None:
    with pytest.raises(ReplyFormatError):
        parse_reply_date(value)


def test_amount_parsing() -> None:
    assert parse_amount("118.00") == Decimal("118.00")
    assert parse_amount(Decimal("32.40")) == Decimal("32.40")
    assert parse_amount(118) == Decimal("118")
    assert parse_amount("null") is None
    with pytest.raises(ReplyFormatError):
        parse_amount(118.0)
    with pytest.raises(ReplyFormatError):
        parse_amount("abc")


def test_message_classifier() -> None:
    assert classify_message("Token expired") == ErrorCategory.AUTH
    assert classify_message("No record found") == ErrorCategory.NOT_FOUND
    assert classify_message("Mobile is mandatory") == ErrorCategory.VALIDATION
    assert classify_message("Age not covered") == ErrorCategory.BUSINESS_RULE
