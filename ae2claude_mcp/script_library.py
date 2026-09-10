"""Persistent exact-content JSX candidates, promotion and safe replay metadata.

No script results are stored. Capture is best-effort and never retries an AE write.
SQLite transactions make deduplication and usage updates safe across MCP processes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TYPE_CHECKING
if TYPE_CHECKING:
    import sqlite3

MAX_CODE_BYTES = 1_000_000
CANDIDATE_TTL = 7 * 24 * 3600
MAX_CANDIDATES = 200
_SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})|"
    r"(?i:(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*['\"][^'\"]{12,}['\"])")


def _root() -> Path:
    configured = os.environ.get("AE2CLAUDE_LIBRARY_DIR")
    if configured:
        return Path(configured).expanduser()
    # Tool-owned persistent state; deliberately excluded from source control.
    return Path(__file__).resolve().parents[1] / "state" / "script-library"


@contextmanager
def _database():
    import sqlite3
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "library.sqlite3", timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS scripts (
            id TEXT PRIMARY KEY, code TEXT NOT NULL, name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'candidate', source TEXT NOT NULL,
            created REAL NOT NULL, updated REAL NOT NULL,
            capture_count INTEGER NOT NULL DEFAULT 1, use_count INTEGER NOT NULL DEFAULT 0,
            last_used REAL, verified INTEGER NOT NULL DEFAULT 0)""")
        with db:
            db.execute("DELETE FROM scripts WHERE status='candidate' AND updated < ?", (time.time() - CANDIDATE_TTL,))
        yield db
    finally:
        db.close()


def _check_code(code: str) -> None:
    if not code.strip() or len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError("JSX must be nonempty and no larger than 1 MB")
    if _SECRET.search(code):
        raise ValueError("Possible credential detected; script was not stored")


def _id(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _summary(row: sqlite3.Row, include_code: bool = False) -> dict[str, Any]:
    item = {"artifactId": row["id"], "name": row["name"], "description": row["description"],
            "tags": json.loads(row["tags"]), "status": row["status"], "source": row["source"],
            "createdAt": row["created"], "updatedAt": row["updated"],
            "captureCount": row["capture_count"], "useCount": row["use_count"],
            "lastUsedAt": row["last_used"], "verified": bool(row["verified"]),
            "risk": "destructive", "sha256": row["id"]}
    if include_code:
        item["code"] = row["code"]
    return item


def capture(code: str, source: str = "ae_exec") -> dict[str, Any]:
    _check_code(code)
    artifact_id, now = _id(code), time.time()
    with _database() as db, db:
        db.execute("""INSERT INTO scripts(id,code,name,source,created,updated)
            VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            capture_count=capture_count+1,updated=excluded.updated""",
            (artifact_id, code, f"JSX {artifact_id[:12]}", source, now, now))
        db.execute("""DELETE FROM scripts WHERE id IN (
            SELECT id FROM scripts WHERE status='candidate'
            ORDER BY updated DESC LIMIT -1 OFFSET ?)""", (MAX_CANDIDATES,))
    return {"status": "captured", "artifactId": artifact_id, "verified": False}


def capture_success(code: str, result: Any, source: str = "ae_exec") -> dict[str, Any]:
    """A completed evaluation is not visual validation. Explicit failures aren't captured."""
    if reported_failure(result):
        return {"status": "skipped", "reason": "script_reported_failure"}
    if os.environ.get("AE2CLAUDE_CAPTURE_SCRIPTS", "1") == "0":
        return {"status": "disabled"}
    try:
        return capture(code, source)
    except Exception:
        # Don't expose script/credentials, and don't turn a completed AE write into
        # a tool error that the caller might mistakenly retry.
        return {"status": "skipped", "reason": "capture_unavailable_or_ineligible"}


def reported_failure(result: Any) -> bool:
    parsed = result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            pass
    return parsed is False or (isinstance(parsed, dict) and
                           (parsed.get("ok") is False or parsed.get("success") is False or
                            parsed.get("outcome") == "unknown"))


def get_script(artifact_id: str, include_code: bool = True) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", artifact_id):
        raise ValueError("Invalid artifact ID")
    with _database() as db:
        row = db.execute("SELECT * FROM scripts WHERE id=?", (artifact_id,)).fetchone()
    if row is None:
        raise ValueError("Script not found or candidate expired")
    if _id(row["code"]) != artifact_id:
        raise ValueError("Stored script hash mismatch; replay refused")
    return _summary(row, include_code)


def search(query: str = "", status: str = "saved", limit: int = 50) -> dict[str, Any]:
    if status not in {"saved", "candidate", "archived", "all"}:
        raise ValueError("status must be saved, candidate, archived or all")
    if not 1 <= limit <= 200:
        raise ValueError("limit must be 1-200")
    with _database() as db:
        # Search metadata only; do not expose unrelated captured source code.
        rows = db.execute("SELECT * FROM scripts ORDER BY updated DESC").fetchall()
    words = query.casefold().split()
    matches = [r for r in rows if (status == "all" or r["status"] == status) and
               all(w in (r["name"] + " " + r["description"] + " " + r["tags"]).casefold() for w in words)]
    return {"ok": True, "total": len(matches), "scripts": [_summary(r) for r in matches[:limit]]}


def save(artifact_id: str, name: str, description: str = "", tags: list[str] | None = None,
         verified: bool = False) -> dict[str, Any]:
    get_script(artifact_id)
    if not name.strip() or len(name) > 160 or len(description) > 4000:
        raise ValueError("Provide a name (1-160 chars) and description (up to 4000 chars)")
    tags = tags or []
    if len(tags) > 30 or any(len(t) > 100 for t in tags):
        raise ValueError("At most 30 tags, each up to 100 characters")
    if _SECRET.search(name + "\n" + description + "\n" + " ".join(tags)):
        raise ValueError("Possible credential in metadata; not saved")
    with _database() as db, db:
        db.execute("UPDATE scripts SET name=?,description=?,tags=?,verified=?,status='saved',updated=? WHERE id=?",
                   (name.strip(), description, json.dumps(tags, ensure_ascii=False), int(verified), time.time(), artifact_id))
    return {"ok": True, "script": get_script(artifact_id, include_code=False)}


def record_use(artifact_id: str) -> None:
    with _database() as db, db:
        db.execute("UPDATE scripts SET use_count=use_count+1,last_used=? WHERE id=?", (time.time(), artifact_id))


def capture_method(method: str, args: list[Any], kwargs: dict[str, Any], result: Any) -> dict[str, Any] | None:
    if method not in {"run_jsx", "run_jsx_checked"}:
        return None
    code = kwargs.get("code", args[0] if args else None)
    if not isinstance(code, str):
        return None
    return capture_success(code, result, method)


def archive(artifact_id: str) -> dict[str, Any]:
    get_script(artifact_id)
    with _database() as db, db:
        db.execute("UPDATE scripts SET status='archived',updated=? WHERE id=?", (time.time(), artifact_id))
    return {"ok": True, "artifactId": artifact_id, "status": "archived"}
