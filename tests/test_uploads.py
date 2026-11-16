"""Upload limits (audit finding 7): bodies over 14 MB are refused before reading; bytes must match the extension."""

import base64
import json

import pytest
from sqlalchemy.orm import Session

from app.body_limit import MAX_BODY_BYTES
from app.main import MAX_UPLOAD_BYTES
from app.models import AuditLog, Document
from tests.asgi_client import call
from tests.test_api import CLERK, Env

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PDF = b"%PDF-1.7\n" + b"0" * 32


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def _upload(env, filename, content, headers=None):
    body = {"doc_type": "identity_proof", "filename": filename, "content_base64": base64.b64encode(content).decode()}
    return call(env.app, "POST", "/cases/LA-01/documents", body, {**CLERK, **(headers or {})})


def _stored(env):
    files = [p for p in env.uploads.rglob("*") if p.is_file()] if env.uploads.exists() else []
    with Session(env.engine) as s:
        return len(files), s.query(Document).count(), s.query(AuditLog).filter_by(action="add_document").count()


@pytest.mark.parametrize("filename, content", [("scan.png", PNG), ("scan.jpg", JPG), ("scan.JPEG", JPG),
                                               ("scan.pdf", PDF), ("id.txt", "Name: Asha Naik, ಆಶಾ".encode())])
def test_files_whose_bytes_match_the_extension_are_accepted(env, filename, content):
    assert _upload(env, filename, content)[0] == 201


@pytest.mark.parametrize("filename, content, why", [
    ("scan.png", b"Name: Asha Naik", "not a .png file"),       # text renamed to .png
    ("scan.pdf", PNG, "not a .pdf file"),                       # an image renamed to .pdf
    ("scan.jpg", b"MZ\x90\x00" + b"\x00" * 32, "not a .jpg file"),   # a Windows program renamed to .jpg
    ("id.txt", b"Name\x00Asha", "binary data"),
    ("id.txt", b"\xff\xfe\xfa not utf-8", "not UTF-8"),
])
def test_bytes_that_do_not_match_the_extension_are_refused_and_nothing_is_stored(env, filename, content, why):
    before = _stored(env)
    status, body = _upload(env, filename, content)
    assert status == 400 and why in body["detail"]
    assert _stored(env) == before


def test_a_file_of_exactly_10_mb_is_accepted_and_one_byte_more_is_refused(env):
    assert _upload(env, "big.png", PNG + b"\x00" * (MAX_UPLOAD_BYTES - len(PNG)))[0] == 201
    status, body = _upload(env, "big.png", PNG + b"\x00" * (MAX_UPLOAD_BYTES - len(PNG) + 1))
    assert status == 400 and "too large" in body["detail"]


def test_a_body_declared_over_the_limit_is_refused_before_it_is_read(env):
    oversized, before = MAX_BODY_BYTES + 1, _stored(env)
    status, body = call(env.app, "POST", "/cases/LA-01/documents", {"doc_type": "identity_proof"},
                        {**CLERK, "content-length": str(oversized)})
    assert status == 413 and "max 14 MB" in body["detail"]
    assert _stored(env) == before


def test_a_body_over_the_limit_without_a_declared_length_is_cut_off(env):
    padding, before = "A" * (MAX_BODY_BYTES + 10), _stored(env)   # valid base64 characters, far too many
    status, body = call(env.app, "POST", "/cases/LA-01/documents",
                        {"doc_type": "identity_proof", "filename": "x.png", "content_base64": padding}, CLERK)
    assert status == 413 and _stored(env) == before


def test_the_limit_leaves_room_for_the_largest_allowed_file():
    as_json = json.dumps({"doc_type": "identity_proof", "filename": "x.png",
                          "content_base64": "A" * (4 * -(-MAX_UPLOAD_BYTES // 3))})
    assert len(as_json) < MAX_BODY_BYTES
