"""Hash-chained audit log: every row stores prev_hash and row_hash = SHA-256(prev_hash + "|" + canonical row).

Canonical row (hand-written below, not taken from the code): a compact JSON list of
[id, ts as stored by SQLite "YYYY-MM-DD HH:MM:SS.ffffff", case_id, actor, action, payload_json, rules_version].
The first row's prev_hash is 64 zeros. Tampering is simulated the way someone with the database file would do it:
drop the append-only triggers, then edit, delete or reorder rows directly."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.audit import log_action
from app.audit_chain import GENESIS, verify_chain
from app.main import create_app
from app.models import AuditLog, make_engine
from tests.asgi_client import call
from tests.auth_headers import staff

ZERO = "0" * 64


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "chain.db"
    engine = make_engine(f"sqlite:///{path}")
    with Session(engine) as s:
        for i in range(1, 6):
            log_action(s, "LA-01", "officer:O-1", f"step_{i}", {"n": i}, "0.1.0")
        s.commit()
    return engine, path


def _raw(path):
    """A plain sqlite3 connection with the append-only triggers removed (the tamperer's view)."""
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER audit_log_no_update")
    conn.execute("DROP TRIGGER audit_log_no_delete")
    return conn


def _verify(engine):
    with Session(engine) as s:
        return verify_chain(s)


# --- the hash itself, against a hand-written canonical row ------------------------------------------------

def test_first_row_hash_matches_the_hand_written_canonical_form(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'one.db'}")
    with Session(engine) as s:
        s.add(AuditLog(case_id="LA-01", actor="officer:O-1", action="x", payload_json='{"a": 1}',
                       rules_version="0.1.0", ts=datetime(2026, 11, 18, 10, 0, 0, tzinfo=timezone.utc)))
        s.commit()
        row = s.query(AuditLog).one()
    canonical = '[1,"2026-11-18 10:00:00.000000","LA-01","officer:O-1","x","{\\"a\\": 1}","0.1.0"]'
    assert GENESIS == ZERO
    assert row.prev_hash == ZERO
    assert row.row_hash == _sha(ZERO + "|" + canonical)


def test_second_row_chains_on_the_first(db):
    engine, _ = db
    with Session(engine) as s:
        first, second = s.query(AuditLog).order_by(AuditLog.id).limit(2).all()
    assert second.prev_hash == first.row_hash
    canonical = json.dumps([2, second.ts.strftime("%Y-%m-%d %H:%M:%S.%f"), "LA-01", "officer:O-1", "step_2",
                            '{"n": 2}', "0.1.0"], ensure_ascii=False, separators=(",", ":"))
    assert second.row_hash == _sha(first.row_hash + "|" + canonical)


def test_rows_added_in_one_flush_chain_in_order(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'batch.db'}")
    with Session(engine) as s:
        for i in range(3):
            log_action(s, None, "agent", f"a{i}", {}, None)
        s.commit()
        rows = s.query(AuditLog).order_by(AuditLog.id).all()
    assert [r.action for r in rows] == ["a0", "a1", "a2"]
    assert rows[0].prev_hash == ZERO and rows[1].prev_hash == rows[0].row_hash
    assert rows[2].prev_hash == rows[1].row_hash
    assert _verify(engine) == {"ok": True, "rows": 3, "first_broken_id": None}


# --- verification ---------------------------------------------------------------------------------------

def test_untouched_chain_passes(db):
    assert _verify(db[0]) == {"ok": True, "rows": 5, "first_broken_id": None}


def test_empty_log_passes(tmp_path):
    assert _verify(make_engine(f"sqlite:///{tmp_path / 'empty.db'}")) == {"ok": True, "rows": 0,
                                                                         "first_broken_id": None}


def test_editing_one_stored_row_fails_at_that_row(db):
    engine, path = db
    conn = _raw(path)
    conn.execute("""UPDATE audit_log SET payload_json = '{"n": 300}' WHERE id = 3""")
    conn.commit()
    conn.close()
    assert _verify(engine) == {"ok": False, "rows": 5, "first_broken_id": 3}


def test_editing_a_row_and_its_own_hash_still_fails_at_the_next_row(db):
    engine, path = db
    conn = _raw(path)
    ts, = conn.execute("SELECT ts FROM audit_log WHERE id = 3").fetchone()
    prev, = conn.execute("SELECT prev_hash FROM audit_log WHERE id = 3").fetchone()
    canonical = json.dumps([3, ts, "LA-01", "officer:O-1", "step_3", '{"n": 300}', "0.1.0"],
                           ensure_ascii=False, separators=(",", ":"))
    conn.execute("UPDATE audit_log SET payload_json = ?, row_hash = ? WHERE id = 3",
                 ('{"n": 300}', _sha(prev + "|" + canonical)))
    conn.commit()
    conn.close()
    assert _verify(engine) == {"ok": False, "rows": 5, "first_broken_id": 4}


def test_deleting_a_middle_row_fails_at_the_row_after_it(db):
    engine, path = db
    conn = _raw(path)
    conn.execute("DELETE FROM audit_log WHERE id = 3")
    conn.commit()
    conn.close()
    assert _verify(engine) == {"ok": False, "rows": 4, "first_broken_id": 4}


def test_reordering_rows_fails_at_the_first_moved_row(db):
    engine, path = db
    conn = _raw(path)
    conn.execute("UPDATE audit_log SET id = 99 WHERE id = 2")
    conn.execute("UPDATE audit_log SET id = 2 WHERE id = 4")
    conn.execute("UPDATE audit_log SET id = 4 WHERE id = 99")
    conn.commit()
    conn.close()
    assert _verify(engine) == {"ok": False, "rows": 5, "first_broken_id": 2}


def test_new_rows_after_tampering_do_not_repair_the_chain(db):
    engine, path = db
    conn = _raw(path)
    conn.execute("DELETE FROM audit_log WHERE id = 3")
    conn.commit()
    conn.close()
    with Session(engine) as s:
        log_action(s, None, "agent", "later", {}, None)
        s.commit()
    assert _verify(engine) == {"ok": False, "rows": 5, "first_broken_id": 4}


def test_the_table_stays_append_only(db):
    engine, path = db
    conn = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE audit_log SET actor = 'x' WHERE id = 1")
    conn.close()


# --- migration of a database created before the chain ---------------------------------------------------

LEGACY_SCHEMA = """
CREATE TABLE audit_log (id INTEGER NOT NULL PRIMARY KEY, ts DATETIME NOT NULL, case_id VARCHAR, actor VARCHAR NOT NULL,
  action VARCHAR NOT NULL, payload_json VARCHAR NOT NULL, rules_version VARCHAR);
CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


def _legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    for i, ts in enumerate(["2026-11-10 09:00:00.000000", "2026-11-10 09:05:00.123456", "2026-11-11 12:00:00.000000"], 1):
        conn.execute("INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (i, ts, "LA-01" if i < 3 else None, "agent", f"old_{i}", "{}", "0.1.0" if i != 2 else None))
    conn.commit()
    conn.close()


def test_migration_computes_the_chain_over_existing_rows_in_order(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_db(path)
    engine = make_engine(f"sqlite:///{path}")
    with Session(engine) as s:
        rows = s.query(AuditLog).order_by(AuditLog.id).all()
    c1 = '[1,"2026-11-10 09:00:00.000000","LA-01","agent","old_1","{}","0.1.0"]'
    c2 = '[2,"2026-11-10 09:05:00.123456","LA-01","agent","old_2","{}",null]'
    c3 = '[3,"2026-11-11 12:00:00.000000",null,"agent","old_3","{}","0.1.0"]'
    h1 = _sha(ZERO + "|" + c1)
    h2 = _sha(h1 + "|" + c2)
    h3 = _sha(h2 + "|" + c3)
    assert [(r.prev_hash, r.row_hash) for r in rows] == [(ZERO, h1), (h1, h2), (h2, h3)]
    assert _verify(engine) == {"ok": True, "rows": 3, "first_broken_id": None}
    with Session(engine) as s:
        log_action(s, None, "agent", "new", {}, None)
        s.commit()
        assert s.query(AuditLog).order_by(AuditLog.id.desc()).first().prev_hash == h3
    conn = sqlite3.connect(path)        # the triggers are back after the migration
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM audit_log WHERE id = 1")
    conn.close()


def test_migration_never_fills_in_a_row_added_later_without_a_hash(db):
    engine, path = db
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO audit_log (id, ts, actor, action, payload_json) "
                 "VALUES (6, '2026-11-18 10:00:00.000000', 'x', 'slipped_in', '{}')")
    conn.commit()
    conn.close()
    engine = make_engine(f"sqlite:///{path}")      # a restart runs the migration again
    assert _verify(engine) == {"ok": False, "rows": 6, "first_broken_id": 6}


# --- API -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["officer", "admin"])
def test_verify_endpoint_for_officer_and_admin(db, tmp_path, role):
    engine, _ = db
    app = create_app(engine=engine, upload_dir=tmp_path)
    status, body = call(app, "GET", "/admin/audit/verify", headers=staff(role, "U-1"))
    assert (status, body) == (200, {"ok": True, "rows": 5, "first_broken_id": None})
    with Session(engine) as s:                     # the check itself is logged, after it ran
        row = s.query(AuditLog).order_by(AuditLog.id.desc()).first()
        assert (row.action, json.loads(row.payload_json)) == ("audit_chain_verified",
                                                               {"ok": True, "rows": 5, "first_broken_id": None})
    assert _verify(engine)["ok"] is True


def test_verify_endpoint_reports_the_broken_row(db, tmp_path):
    engine, path = db
    conn = _raw(path)
    conn.execute("DELETE FROM audit_log WHERE id = 2")
    conn.commit()
    conn.close()
    status, body = call(create_app(engine=engine, upload_dir=tmp_path), "GET", "/admin/audit/verify",
                        headers=staff("officer", "O-1"))
    assert (status, body) == (200, {"ok": False, "rows": 4, "first_broken_id": 3})


def test_verify_endpoint_refuses_clerk_and_anonymous(db, tmp_path):
    app = create_app(engine=db[0], upload_dir=tmp_path)
    assert call(app, "GET", "/admin/audit/verify", headers=staff("clerk", "C-1"))[0] == 403
    assert call(app, "GET", "/admin/audit/verify")[0] == 401
