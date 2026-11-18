"""Hash chain over audit_log (CLAUDE.md rule 5): each row stores prev_hash and
row_hash = SHA-256(prev_hash + "|" + canonical row). The first row's prev_hash is GENESIS.

The canonical row is a compact JSON list of [id, ts, case_id, actor, action, payload_json, rules_version], with ts
exactly as SQLite stores it ("YYYY-MM-DD HH:MM:SS.ffffff", time zone dropped, as SQLAlchemy writes it). Verification
reads the stored text, so the hash never depends on how a datetime is parsed back.

What it shows: a stored row edited, deleted or moved. What it cannot show on its own: the newest rows removed from
the end, or the whole chain recomputed by someone with the file (no secret key; see KNOWN_LIMITATIONS)."""

import hashlib
import json
from datetime import datetime
from typing import Any, Optional, Sequence

GENESIS = "0" * 64
COLUMNS = "id, ts, case_id, actor, action, payload_json, rules_version"


def stored_ts(ts: datetime) -> str:
    """The text SQLAlchemy's SQLite DateTime writes for `ts` (tzinfo is not converted, only dropped)."""
    return (f"{ts.year:04d}-{ts.month:02d}-{ts.day:02d} "
            f"{ts.hour:02d}:{ts.minute:02d}:{ts.second:02d}.{ts.microsecond:06d}")


def canonical(row: Sequence[Any]) -> str:
    """`row`: id, ts (stored text), case_id, actor, action, payload_json, rules_version."""
    return json.dumps(list(row), ensure_ascii=False, separators=(",", ":"))


def row_hash(prev_hash: str, row: Sequence[Any]) -> str:
    return hashlib.sha256(f"{prev_hash}|{canonical(row)}".encode("utf-8")).hexdigest()


def check_rows(rows: Sequence[Sequence[Any]]) -> dict[str, Any]:
    """`rows` in id order, each the COLUMNS values followed by prev_hash and row_hash."""
    prev = GENESIS
    for r in rows:
        fields, stored_prev, stored_hash = r[:7], r[7], r[8]
        if stored_prev != prev or stored_hash != row_hash(prev, fields):
            return {"ok": False, "rows": len(rows), "first_broken_id": r[0]}
        prev = stored_hash
    return {"ok": True, "rows": len(rows), "first_broken_id": None}


def verify_chain(session: Any) -> dict[str, Any]:
    """ok, row count and the id of the first row that does not chain, read straight from the table."""
    rows = session.connection().exec_driver_sql(
        f"SELECT {COLUMNS}, prev_hash, row_hash FROM audit_log ORDER BY id").fetchall()
    return check_rows(rows)


def chain_new_rows(conn: Any, new_rows: list[Any]) -> None:
    """Give pending AuditLog objects (in insertion order) their id, ts, prev_hash and row_hash before insert."""
    last = conn.exec_driver_sql("SELECT id, row_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    last_id, prev = (last[0], last[1] or GENESIS) if last else (0, GENESIS)
    for obj in new_rows:
        last_id += 1
        obj.id = last_id
        fields = (obj.id, stored_ts(obj.ts), obj.case_id, obj.actor, obj.action, obj.payload_json,
                  obj.rules_version)
        obj.prev_hash = prev
        obj.row_hash = prev = row_hash(prev, fields)


def backfill(conn: Any, trigger_sql: dict[str, str]) -> Optional[int]:
    """Migration: compute the chain over rows written before it existed, in id order. Runs only when no row has a
    hash yet, so a row slipped in later without one is never filled in (verification reports it instead)."""
    if conn.exec_driver_sql("SELECT COUNT(*) FROM audit_log WHERE row_hash IS NOT NULL").scalar():
        return None
    rows = conn.exec_driver_sql(f"SELECT {COLUMNS} FROM audit_log ORDER BY id").fetchall()
    if not rows:
        return 0
    conn.exec_driver_sql("DROP TRIGGER IF EXISTS audit_log_no_update")
    prev = GENESIS
    for r in rows:
        h = row_hash(prev, r)
        conn.exec_driver_sql("UPDATE audit_log SET prev_hash = ?, row_hash = ? WHERE id = ?", (prev, h, r[0]))
        prev = h
    conn.exec_driver_sql(trigger_sql["UPDATE"])
    return len(rows)
