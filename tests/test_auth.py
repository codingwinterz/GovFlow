"""Demo sign-in tokens (audit finding 1): signed, expiring, and the only accepted identity unless insecure mode."""

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import TOKEN_TTL, issue_token, read_token
from app.main import create_app
from app.models import AuditLog, Base
from tests.asgi_client import call
from tests.auth_headers import TEST_AUTH_SECRET, staff

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
PLAIN_OFFICER = {"X-Role": "officer", "X-User": "O-1"}


def _engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


def _app(tmp_path, clock=lambda: NOW, **kwargs):
    return create_app(engine=_engine(), upload_dir=tmp_path, now=lambda: clock(), **kwargs)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# --- the token itself --------------------------------------------------------------------------------------------

def test_a_token_carries_role_and_user_until_it_expires():
    token, expires = issue_token("officer", "O-1", "s3cret", NOW)
    assert expires == NOW + TOKEN_TTL == NOW + timedelta(hours=8)
    assert read_token(token, "s3cret", NOW) == ("officer", "O-1")
    assert read_token(token, "s3cret", expires - timedelta(seconds=1)) == ("officer", "O-1")
    assert read_token(token, "s3cret", expires) is None                       # expired at exp


def test_an_edited_or_foreign_token_is_refused():
    token, _ = issue_token("clerk", "C-1", "s3cret", NOW)
    body, sig = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    forged = base64.urlsafe_b64encode(json.dumps({**claims, "role": "officer"}).encode()).rstrip(b"=").decode()
    assert read_token(f"{forged}.{sig}", "s3cret", NOW) is None              # role edited: signature no longer fits
    assert read_token(token, "other-secret", NOW) is None                      # signed by someone else
    for junk in ["", ".", "abc", f"{body}.", f".{sig}", "a.b.c"]:
        assert read_token(junk, "s3cret", NOW) is None


# --- the API ------------------------------------------------------------------------------------------------------

def test_demo_sign_in_issues_a_token_the_api_accepts_and_audits_it(tmp_path):
    app = _app(tmp_path)
    status, body = call(app, "POST", "/auth/demo-login", {"role": "officer", "user": "O-9"})
    assert status == 200 and body["role"] == "officer" and body["expires_at"] == "2026-11-16T17:00:00Z"
    assert call(app, "GET", "/cases", headers=_bearer(body["token"]))[0] == 200


def test_sign_in_is_recorded_in_the_audit_log(tmp_path):
    engine = _engine()
    app = create_app(engine=engine, upload_dir=tmp_path, now=lambda: NOW)
    call(app, "POST", "/auth/demo-login", {"role": "clerk", "user": "C-2"})
    with Session(engine) as s:
        (row,) = s.query(AuditLog).filter_by(action="demo_sign_in").all()
    assert row.actor == "clerk:C-2" and row.case_id is None


@pytest.mark.parametrize("body", [{"role": "citizen", "user": "P-1"}, {"role": "superuser", "user": "x"},
                                  {"role": "officer", "user": ""}, {"role": "officer", "user": "a b"}])
def test_sign_in_only_for_staff_roles_and_plain_user_ids(tmp_path, body):
    assert call(_app(tmp_path), "POST", "/auth/demo-login", body)[0] == 422


def test_plain_role_headers_are_refused_by_default(tmp_path):
    status, body = call(_app(tmp_path), "GET", "/cases", headers=PLAIN_OFFICER)
    assert status == 401 and "GOVFLOW_DEMO_INSECURE" in body["detail"] and "Bearer" in body["detail"]


@pytest.mark.parametrize("how", ["argument", "environment"])
def test_plain_role_headers_work_only_in_insecure_demo_mode(tmp_path, monkeypatch, how):
    if how == "environment":
        monkeypatch.setenv("GOVFLOW_DEMO_INSECURE", "1")
        app = _app(tmp_path)
    else:
        app = _app(tmp_path, demo_insecure=True)
    assert call(app, "GET", "/cases", headers=PLAIN_OFFICER)[0] == 200


def test_a_forged_or_expired_token_is_refused(tmp_path):
    clock = {"now": NOW}
    app = _app(tmp_path, clock=lambda: clock["now"])
    token, _ = issue_token("clerk", "C-1", TEST_AUTH_SECRET, NOW)
    body, sig = token.split(".")
    forged = base64.urlsafe_b64encode(json.dumps({"role": "officer", "user": "C-1", "exp": 9_999_999_999}).encode())
    assert call(app, "GET", "/cases", headers=_bearer(f"{forged.rstrip(b'=').decode()}.{sig}"))[0] == 401
    assert call(app, "GET", "/cases", headers=_bearer(token))[0] == 200
    clock["now"] = NOW + timedelta(hours=8, seconds=1)
    status, detail = call(app, "GET", "/cases", headers=_bearer(token))
    assert status == 401 and "sign in again" in detail["detail"]


def test_a_valid_token_wins_and_extra_role_headers_cannot_raise_it(tmp_path):
    app = _app(tmp_path, demo_insecure=True)
    clerk = {**staff("clerk", "C-1"), "X-Role": "officer", "X-User": "O-1"}
    assert call(app, "POST", "/cases/LA-01/decision", {"decision": "approve"}, headers=clerk)[0] == 403


def test_without_a_signing_secret_sign_in_is_503_and_no_token_is_accepted(tmp_path, monkeypatch):
    monkeypatch.delenv("GOVFLOW_AUTH_SECRET", raising=False)
    app = _app(tmp_path)
    status, body = call(app, "POST", "/auth/demo-login", {"role": "officer", "user": "O-1"})
    assert status == 503 and "GOVFLOW_AUTH_SECRET" in body["detail"]
    assert call(app, "GET", "/cases", headers=staff("officer", "O-1"))[0] == 401


def test_role_checks_still_apply_to_signed_identities(tmp_path):
    app = _app(tmp_path)
    assert call(app, "POST", "/simulate", {"scheme": "land_acquisition", "name": "multiplier", "value": 1.5},
                headers=staff("clerk", "C-1"))[0] == 403
    assert call(app, "POST", "/cases/LA-01/decision", {"decision": "approve"}, headers=staff("admin", "A-1"))[0] == 403
