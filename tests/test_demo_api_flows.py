"""Builder's end-to-end flows against the demo app (memory backend + fakes). Synthetic data only.

Exercises the happy path to certificate, insurer rejection, CBS unknown outcome with the
two-person operations CONFIRM, and the main access controls. Not a QA verification.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.persistence.memory.seed import read_seed
from backend.platform.config import Settings
from scaffold_support import logging_guard

SEED = read_seed()
PASSWORD = SEED["bank_auth"]["fake_password"]
BRANCH = {u["roll_no"]: u["branch_code"] for u in SEED["bank_auth"]["users"]}
WRONG = "x" * 3
SECRET = "synthetic-session-secret-for-tests-0123456789"  # secret-scan:allow


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    yield from logging_guard()


@pytest.fixture
def app() -> Any:
    settings = Settings(
        env="demo",
        session_secret=SECRET,  # type: ignore[arg-type]
        fake_delay_ms=0,
        job_worker_enabled=False,
        retry_delay_seconds=0,
        cbs_timeout_seconds=0.01,
        throttle_enabled=False,
    )
    return create_app(settings)


class User:
    def __init__(self, app: Any, roll: str) -> None:
        self.client = TestClient(app, base_url="https://testserver")
        response = self.client.post(
            "/api/v1/auth/login",
            json={"branch_code": BRANCH[roll], "roll_no": roll, "password": PASSWORD},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "SIGNED_IN"
        self.me = body["me"]
        self.csrf = body["me"]["csrf_token"]

    def get(self, path: str, **kw: Any) -> Any:
        return self.client.get("/api/v1" + path, **kw)

    def post(self, path: str, body: Any = None, *, key: str | bool | None = True) -> Any:
        headers = {"X-CSRF-Token": self.csrf}
        if key is True:
            headers["Idempotency-Key"] = str(uuid.uuid4())
        elif isinstance(key, str):
            headers["Idempotency-Key"] = key
        return self.client.post("/api/v1" + path, json=body, headers=headers)

    def patch(self, path: str, body: Any) -> Any:
        return self.client.patch("/api/v1" + path, json=body, headers={"X-CSRF-Token": self.csrf})


def draft(maker: User, account_no: str, plan: str = "A") -> dict[str, Any]:
    found = maker.post("/customers/lookup", {"account_no": account_no}, key=False)
    assert found.status_code == 200, found.text
    account = next(
        a for a in found.json()["accounts"] if a["account_no_masked"].endswith(account_no[-4:])
    )
    assert account_no not in found.text  # never the full number
    created = maker.post(
        "/enrolments",
        {
            "lookup": {"account_no": account_no},
            "debit_account_key": account["account_key"],
            "plan_code": plan,
        },
    )
    assert created.status_code == 201, created.text
    e = created.json()
    patch: dict[str, Any] = {
        "version": e["version"],
        "nominees": [
            {"name": "Synthetic Nominee", "relation_code": "SPOUSE", "share_percent": "100"}
        ],
    }
    if "occupation_code" not in e["insured"]["cbs_sourced_fields"]:
        patch["insured"] = {"occupation_code": "SALARIED", "any_disability": False}
    else:
        patch["insured"] = {"any_disability": False}
    updated = maker.patch(f"/enrolments/{e['enrolment_id']}", patch)
    assert updated.status_code == 200, updated.text
    result: dict[str, Any] = updated.json()
    return result


def approved(maker: User, checker: User, account_no: str) -> dict[str, Any]:
    e = draft(maker, account_no)
    submitted = maker.post(
        f"/enrolments/{e['enrolment_id']}/submit", {"version": e["version"]}, key=False
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["enrolment"]["status"] == "PENDING_CHECK"
    queue = checker.get("/approvals").json()["items"]
    approval = next(a for a in queue if a["entity_id"] == e["enrolment_id"])
    assert approval["can_decide"] is True
    done = checker.post(f"/approvals/{approval['approval_id']}/approve", {"comment": "ok"})
    assert done.status_code == 200, done.text
    result: dict[str, Any] = done.json()["enrolment"]
    assert result["status"] == "APPROVED"
    return result


def to_proposal(maker: User, checker: User, account_no: str) -> dict[str, Any]:
    e = approved(maker, checker, account_no)
    response = maker.post(f"/enrolments/{e['enrolment_id']}/proposal", {"version": e["version"]})
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def pay(maker: User, e: dict[str, Any]) -> dict[str, Any]:
    eid = e["enrolment_id"]
    consent = maker.post(
        f"/enrolments/{eid}/consent",
        {
            "version": e["version"],
            "method": "SIGNED_FORM",
            "reference": "SYN-FORM-1",
            "confirmed_amount": e["premium"]["gross_premium"],
        },
        key=False,
    )
    assert consent.status_code == 200, consent.text
    e = consent.json()["enrolment"]
    assert "POST_PAYMENT" in e["allowed_actions"]
    response = maker.post(f"/enrolments/{eid}/payment", {"version": e["version"]})
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def test_happy_path_to_certificate(app: Any) -> None:
    maker, checker = User(app, "D1001"), User(app, "D1002")
    assert maker.me["environment"] == {"mode": "demo", "synthetic_data": True}
    assert maker.get("/reference/plans").json()["items"][0]["rate"]["synthetic"] is True
    proposal = to_proposal(maker, checker, "509900011001")
    e = proposal["enrolment"]
    assert proposal["outcome"]["result"] == "DONE"
    assert e["status"] == "PROPOSAL_CREATED"
    assert e["premium"] == {
        "net_premium": "100.00",
        "gst_amount": "18.00",
        "gross_premium": "118.00",
        "matches_rate": True,
    }
    paid = pay(maker, e)
    assert paid["outcome"]["result"] == "DONE"
    e = paid["enrolment"]
    assert e["status"] == "ISSUED"
    assert e["certificate"]["pdf_available"] is True
    assert [p["status"] for p in e["postings"]] == ["SUCCESS"]
    pdf = maker.get(f"/enrolments/{e['enrolment_id']}/certificate")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert b"SPECIMEN" in pdf.content
    history = [h["to_status"] for h in e["status_history"]]
    assert history == [
        "DRAFT",
        "PENDING_CHECK",
        "APPROVED",
        "PROPOSAL_CREATED",
        "PAYMENT_PENDING",
        "PAID",
        "ISSUED",
    ]
    container = app.state.container
    with container.deps.uow() as uow:
        assert uow.audit.verify_chain()
    dashboard = maker.get("/dashboard").json()
    assert dashboard["kpis"]["issued_today"] >= 2
    assert "awaiting_my_approval" not in dashboard["queues"]


def test_idempotent_replay_and_key_reuse(app: Any) -> None:
    maker, checker = User(app, "D1001"), User(app, "D1002")
    e = approved(maker, checker, "509900021003")
    key = str(uuid.uuid4())
    first = maker.post(
        f"/enrolments/{e['enrolment_id']}/proposal", {"version": e["version"]}, key=key
    )
    again = maker.post(
        f"/enrolments/{e['enrolment_id']}/proposal", {"version": e["version"]}, key=key
    )
    assert first.status_code == again.status_code == 200
    assert again.json()["outcome"]["replayed"] is True
    other = maker.post(f"/enrolments/{e['enrolment_id']}/proposal", {"version": 99}, key=key)
    assert other.status_code == 422
    assert other.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    insurer = app.state.container.fakes["insurer"]
    assert insurer.calls.count("create_proposal") == 1


def test_insurer_rejection_then_reopen(app: Any) -> None:
    maker, checker = User(app, "D1009"), User(app, "D1003")
    result = to_proposal(maker, checker, "509900076001")  # ...6001: insurer rejects
    assert result["outcome"]["result"] == "REJECTED"
    assert result["outcome"]["category"] == "VALIDATION"
    assert result["outcome"]["message"]
    e = result["enrolment"]
    assert e["status"] == "PROPOSAL_REJECTED"
    assert e["allowed_actions"] == ["REOPEN"]
    reopened = maker.post(
        f"/enrolments/{e['enrolment_id']}/reopen", {"version": e["version"]}, key=False
    )
    assert reopened.json()["enrolment"]["status"] == "DRAFT"


def test_cbs_unknown_then_two_person_confirm(app: Any) -> None:
    maker, checker = User(app, "D1001"), User(app, "D1002")
    ops1, ops2 = User(app, "D1004"), User(app, "D1008")
    result = pay(maker, to_proposal(maker, checker, "509900067003")["enrolment"])  # ...7003
    assert result["outcome"]["result"] == "NEEDS_ATTENTION"
    e = result["enrolment"]
    assert e["status"] == "NEEDS_ATTENTION"
    assert e["attention"]["reason"] == "POSTING_UNKNOWN"
    assert [p["status"] for p in e["postings"]] == ["UNKNOWN"]
    eid = e["enrolment_id"]
    queue = ops1.get("/operations/attention?reason=POSTING_UNKNOWN").json()["items"]
    assert any(item["enrolment_id"] == eid for item in queue)
    recheck = ops1.post(
        f"/operations/attention/{eid}/resolve", {"version": e["version"], "action": "RECHECK"}
    )
    assert recheck.json()["outcome"]["result"] == "NEEDS_ATTENTION"  # still unclear
    e = recheck.json()["enrolment"]
    confirm = ops1.post(
        f"/operations/attention/{eid}/resolve",
        {
            "version": e["version"],
            "action": "CONFIRM",
            "target_status": "PAID",
            "note": "Bank confirmed the debit",
            "evidence_ref": "SYN-TICKET-1",
        },
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["outcome"]["result"] == "PENDING_APPROVAL"
    assert confirm.json()["enrolment"]["status"] == "NEEDS_ATTENTION"
    approval = next(a for a in ops1.get("/approvals").json()["items"] if a["enrolment_id"] == eid)
    assert approval["can_decide"] is False
    own = ops1.post(f"/approvals/{approval['approval_id']}/approve", {})
    assert own.status_code == 403
    assert own.json()["code"] == "MAKER_CANNOT_CHECK"
    done = ops2.post(f"/approvals/{approval['approval_id']}/approve", {"comment": "seen"})
    assert done.status_code == 200, done.text
    assert done.json()["enrolment"]["status"] == "PAID"
    container = app.state.container
    assert container.jobs.run_due() >= 1
    final = maker.get(f"/enrolments/{eid}").json()
    assert final["status"] == "ISSUED"
    assert len(final["postings"]) == 1  # never posted twice


def test_posting_unknown_resolves_by_status_read(app: Any) -> None:
    maker, checker = User(app, "D1001"), User(app, "D1002")
    result = pay(maker, to_proposal(maker, checker, "509900057002")["enrolment"])  # ...7002
    assert result["enrolment"]["status"] == "ISSUED"
    assert len(result["enrolment"]["postings"]) == 1


def test_premium_mismatch_blocks_payment(app: Any) -> None:
    maker, checker = User(app, "D1009"), User(app, "D1003")
    e = to_proposal(maker, checker, "509900086003")["enrolment"]  # ...6003
    assert e["premium"]["matches_rate"] is False
    assert "POST_PAYMENT" not in e["allowed_actions"]
    refused = maker.post(f"/enrolments/{e['enrolment_id']}/payment", {"version": e["version"]})
    assert refused.status_code == 409
    assert refused.json()["code"] == "PREMIUM_MISMATCH"


def test_issue_retries_then_needs_attention(app: Any) -> None:
    maker, checker = User(app, "D1009"), User(app, "D1003")
    result = pay(maker, to_proposal(maker, checker, "509900086005")["enrolment"])  # ...6005
    assert result["outcome"]["result"] == "QUEUED_FOR_RETRY"
    eid = result["enrolment"]["enrolment_id"]
    assert result["enrolment"]["status"] == "PAID"
    container = app.state.container
    for _ in range(container.settings.issue_retry_limit):
        container.deps.clock.advance(timedelta(seconds=1))
        container.jobs.run_due()
    final = maker.get(f"/enrolments/{eid}").json()
    assert final["status"] == "NEEDS_ATTENTION"
    assert final["attention"]["reason"] == "ISSUE_RETRIES_EXHAUSTED"


def test_access_controls(app: Any) -> None:
    anonymous = TestClient(app, base_url="https://testserver")
    assert anonymous.get("/api/v1/me").json()["code"] == "UNAUTHENTICATED"
    maker = User(app, "D1001")
    no_csrf = maker.client.post("/api/v1/customers/lookup", json={"cif": "SYN0001"})
    assert no_csrf.status_code == 403
    assert no_csrf.json()["code"] == "CSRF_FAILED"
    bad_origin = maker.client.post(
        "/api/v1/customers/lookup",
        json={"cif": "SYN0001"},
        headers={"X-CSRF-Token": maker.csrf, "Origin": "https://evil.invalid"},
    )
    assert bad_origin.status_code == 403
    assert (
        maker.post("/customers/lookup", {"cif": "SYN0003"}, key=False).json()["accounts"][0][
            "selectable"
        ]
        is False
    )
    assert maker.post("/customers/lookup", {"cif": "NOPE1"}, key=False).status_code == 404
    unavailable = maker.post("/customers/lookup", {"cif": "SYN9902"}, key=False)
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "CBS_UNAVAILABLE"
    norole = User(app, "D1007")
    assert norole.me["roles"] == []
    assert norole.get("/dashboard").status_code == 403
    east = User(app, "D1003")
    pending = east.get("/approvals").json()["items"]
    own = next(a for a in pending if a["maker"]["roll_no"] == "D1003")
    assert own["can_decide"] is False
    refused = east.post(f"/approvals/{own['approval_id']}/approve", {})
    assert refused.json()["code"] == "MAKER_CANNOT_CHECK"
    west_ids = {i["enrolment_id"] for i in maker.get("/enrolments?page_size=100").json()["items"]}
    east_ids = {i["enrolment_id"] for i in east.get("/enrolments?page_size=100").json()["items"]}
    assert not west_ids & east_ids
    assert east.get(f"/enrolments/{next(iter(west_ids))}").status_code == 404
    wrong = TestClient(app, base_url="https://testserver").post(
        "/api/v1/auth/login",
        json={"branch_code": "0101", "roll_no": "D1001", "password": WRONG},
    )
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "LOGIN_FAILED"
    assert anonymous.get("/docs").status_code == 404


def test_otp_login(app: Any) -> None:
    client = TestClient(app, base_url="https://testserver")
    first = client.post(
        "/api/v1/auth/login", json={"branch_code": "0101", "roll_no": "D9001", "password": PASSWORD}
    )
    assert first.json()["status"] == "OTP_REQUIRED"
    challenge = first.json()["challenge_id"]
    signed = client.post(
        "/api/v1/auth/otp", json={"challenge_id": challenge, "otp": SEED["bank_auth"]["valid_otp"]}
    )
    assert signed.status_code == 200
    assert signed.json()["status"] == "SIGNED_IN"
    cookie = signed.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
    reused = client.post("/api/v1/auth/otp", json={"challenge_id": challenge, "otp": "123456"})
    assert reused.status_code == 401


def test_every_seeded_enrolment_renders_and_dashboards_work(app: Any) -> None:
    auditor = User(app, "D1005")
    page = auditor.get("/enrolments?page_size=100").json()
    assert page["total"] == 26
    for item in page["items"]:
        detail = auditor.get(f"/enrolments/{item['enrolment_id']}")
        assert detail.status_code == 200, detail.text
        if "DOWNLOAD_CERTIFICATE" in detail.json()["allowed_actions"]:
            assert auditor.get(f"/enrolments/{item['enrolment_id']}/certificate").status_code == 200
    for roll in ("D1001", "D1002", "D1003", "D1004", "D1005", "D1006", "D1009"):
        assert User(app, roll).get("/dashboard").status_code == 200, roll
    ops = User(app, "D1004")
    attention = ops.get("/operations/attention").json()["items"]
    assert {i["attention_reason"] for i in attention} == {
        "POSTING_UNKNOWN",
        "ISSUE_RETRIES_EXHAUSTED",
    }
    codes = ops.get("/reference/codes").json()
    assert {c["code"] for c in codes["CONSENT_METHOD"]} == {"SIGNED_FORM", "BRANCH_DECLARATION"}
