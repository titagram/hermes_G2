from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from typing import Any, Optional


ACTIVE_JOB_STATES = {"queued", "running"}
DEFAULT_DB_PATH = os.path.expanduser("~/.hermes-g2/state.sqlite3")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class G2StateStore:
    """SQLite-backed state store for durable G2 bridge sessions."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.getenv("HERMES_G2_STATE_DB") or DEFAULT_DB_PATH
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def resume_session(
        self,
        client_session_id: str,
        profile_id: str,
        target: str = "",
        scope: str = "",
        last_seen_event_id: int = 0,
    ) -> dict[str, Any]:
        client_id = self._validate_identifier(client_session_id, "client_session_id")
        profile = self._validate_identifier(profile_id, "profile_id")
        now = time.time()
        with self._lock:
            row = self._db.execute(
                """
                SELECT * FROM g2_sessions
                WHERE client_session_id = ? AND profile_id = ?
                """,
                (client_id, profile),
            ).fetchone()
            if row is None:
                session_id = f"g2_{uuid.uuid4().hex}"
                self._db.execute(
                    """
                    INSERT INTO g2_sessions
                        (id, client_session_id, profile_id, target, scope, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, client_id, profile, target.strip(), scope.strip(), now, now),
                )
            else:
                session_id = str(row["id"])
                next_target = target.strip() or str(row["target"] or "")
                next_scope = scope.strip() or str(row["scope"] or "")
                self._db.execute(
                    """
                    UPDATE g2_sessions
                    SET target = ?, scope = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (next_target, next_scope, now, session_id),
                )
            self._db.commit()

        session = self.get_session(session_id)
        return {
            "session": session,
            "target": {"target": session["target"], "scope": session["scope"]},
            "pendingApprovals": self.pending_approvals(session_id),
            "activeGrants": self.active_grants(session_id),
            "jobs": self.jobs_for_session(session_id),
            "missedEvents": self.events_since(session_id, last_seen_event_id),
        }

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM g2_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown G2 session: {session_id}")
        return self._session_from_row(row)

    def set_target(self, session_id: str, target: str, scope: str) -> dict[str, str]:
        with self._lock:
            self._db.execute(
                """
                UPDATE g2_sessions
                SET target = ?, scope = ?, updated_at = ?
                WHERE id = ?
                """,
                (target.strip(), scope.strip(), time.time(), session_id),
            )
            self._db.commit()
        return {"target": target.strip(), "scope": scope.strip()}

    def append_event(self, session_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            cursor = self._db.execute(
                """
                INSERT INTO g2_events (session_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, event_type, self._to_json(payload), now),
            )
            self._db.commit()
            event_id = int(cursor.lastrowid)
        return {
            "eventId": event_id,
            "type": event_type,
            "payload": payload,
            "createdAt": int(now * 1000),
        }

    def events_since(self, session_id: str, last_seen_event_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM g2_events
                WHERE session_id = ? AND event_id > ?
                ORDER BY event_id ASC
                LIMIT ?
                """,
                (session_id, max(0, int(last_seen_event_id or 0)), max(1, int(limit))),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def save_approval(
        self,
        session_id: str,
        approval: dict[str, Any],
        prompt: str,
        ttl_seconds: int = 600,
    ) -> dict[str, Any]:
        approval_id = str(approval.get("id") or "").strip()
        if not approval_id:
            raise ValueError("approval id is required")
        now = time.time()
        expires_at = now + max(1, int(ttl_seconds))
        with self._lock:
            self._db.execute(
                """
                INSERT INTO g2_approvals
                    (session_id, approval_id, approval_json, prompt, status, created_at, expires_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(session_id, approval_id) DO UPDATE SET
                    approval_json = excluded.approval_json,
                    prompt = excluded.prompt,
                    status = 'pending',
                    expires_at = excluded.expires_at,
                    resolved_at = NULL
                """,
                (session_id, approval_id, self._to_json(approval), prompt, now, expires_at),
            )
            self._db.commit()
        return {"approval": approval, "prompt": prompt}

    def pending_approvals(self, session_id: str) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM g2_approvals
                WHERE session_id = ? AND status = 'pending' AND expires_at > ?
                ORDER BY created_at ASC
                """,
                (session_id, now),
            ).fetchall()
        return [
            {"approval": self._from_json(row["approval_json"]), "prompt": str(row["prompt"] or "")}
            for row in rows
        ]

    def resolve_approval(self, session_id: str, approval_id: str, status: str) -> None:
        with self._lock:
            self._db.execute(
                """
                UPDATE g2_approvals
                SET status = ?, resolved_at = ?
                WHERE session_id = ? AND approval_id = ?
                """,
                (status, time.time(), session_id, approval_id),
            )
            self._db.commit()

    def save_grant(
        self,
        session_id: str,
        target: str,
        workflow: str,
        risk_ceiling: str,
        ttl_seconds: int,
        source_channel: str = "glasses",
    ) -> dict[str, Any]:
        now = time.time()
        expires_at = now + max(1, int(ttl_seconds))
        with self._lock:
            cursor = self._db.execute(
                """
                INSERT INTO g2_grants
                    (session_id, target, workflow, risk_ceiling, source_channel, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, target, workflow, risk_ceiling, source_channel, now, expires_at),
            )
            self._db.commit()
            grant_id = int(cursor.lastrowid)
        return {
            "id": grant_id,
            "target": target,
            "workflow": workflow,
            "riskCeiling": risk_ceiling,
            "sourceChannel": source_channel,
            "expiresAt": int(expires_at * 1000),
        }

    def active_grants(self, session_id: str) -> list[dict[str, Any]]:
        now = time.time()
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM g2_grants
                WHERE session_id = ? AND expires_at > ?
                ORDER BY created_at DESC
                """,
                (session_id, now),
            ).fetchall()
        return [self._grant_from_row(row) for row in rows]

    def create_job(
        self,
        session_id: str,
        workflow: str,
        target: str,
        state: str = "queued",
        command: Optional[list[str]] = None,
        report_url: str = "",
    ) -> dict[str, Any]:
        now = time.time()
        job_id = f"job_{uuid.uuid4().hex[:16]}"
        with self._lock:
            self._db.execute(
                """
                INSERT INTO g2_jobs
                    (id, session_id, workflow, target, state, command_json, report_url,
                     log_tail, created_at, updated_at, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    job_id,
                    session_id,
                    workflow,
                    target,
                    state,
                    self._to_json(command or []),
                    report_url,
                    now,
                    now,
                    now if state == "running" else None,
                ),
            )
            self._db.commit()
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("SELECT * FROM g2_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown G2 job: {job_id}")
        return self._job_from_row(row)

    def update_job(
        self,
        job_id: str,
        state: Optional[str] = None,
        pid: Optional[int] = None,
        exit_code: Optional[int] = None,
        append_log: Optional[str] = None,
        report_url: Optional[str] = None,
    ) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("SELECT * FROM g2_jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"unknown G2 job: {job_id}")

            log_tail = str(row["log_tail"] or "")
            if append_log:
                log_tail = (log_tail + "\n" + append_log.strip()).strip()
                log_tail = log_tail[-4000:]

            next_state = state or str(row["state"])
            finished_at = row["finished_at"]
            if next_state not in ACTIVE_JOB_STATES and finished_at is None:
                finished_at = time.time()
            started_at = row["started_at"]
            if next_state == "running" and started_at is None:
                started_at = time.time()

            self._db.execute(
                """
                UPDATE g2_jobs
                SET state = ?, pid = COALESCE(?, pid), exit_code = COALESCE(?, exit_code),
                    report_url = COALESCE(?, report_url), log_tail = ?,
                    updated_at = ?, started_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (
                    next_state,
                    pid,
                    exit_code,
                    report_url,
                    log_tail,
                    time.time(),
                    started_at,
                    finished_at,
                    job_id,
                ),
            )
            self._db.commit()
        return self.get_job(job_id)

    def jobs_for_session(self, session_id: str, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM g2_jobs WHERE session_id = ?"
        params: list[Any] = [session_id]
        if active_only:
            query += " AND state IN (?, ?)"
            params.extend(sorted(ACTIVE_JOB_STATES))
        query += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._db.execute(query, params).fetchall()
        return [self._job_from_row(row) for row in rows]

    def active_job(
        self,
        session_id: str,
        workflow: str,
        target: str,
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._db.execute(
                """
                SELECT * FROM g2_jobs
                WHERE session_id = ? AND workflow = ? AND target = ? AND state IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (session_id, workflow, target),
            ).fetchone()
        return self._job_from_row(row) if row else None

    def _migrate(self) -> None:
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS g2_sessions (
                    id TEXT PRIMARY KEY,
                    client_session_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(client_session_id, profile_id)
                );

                CREATE TABLE IF NOT EXISTS g2_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES g2_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS g2_approvals (
                    session_id TEXT NOT NULL,
                    approval_id TEXT NOT NULL,
                    approval_json TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    resolved_at REAL,
                    PRIMARY KEY(session_id, approval_id),
                    FOREIGN KEY(session_id) REFERENCES g2_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS g2_grants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    target TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    risk_ceiling TEXT NOT NULL,
                    source_channel TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES g2_sessions(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS g2_jobs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    target TEXT NOT NULL,
                    state TEXT NOT NULL,
                    command_json TEXT NOT NULL,
                    report_url TEXT NOT NULL DEFAULT '',
                    log_tail TEXT NOT NULL DEFAULT '',
                    pid INTEGER,
                    exit_code INTEGER,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    FOREIGN KEY(session_id) REFERENCES g2_sessions(id) ON DELETE CASCADE
                );
                """
            )
            self._db.commit()

    @staticmethod
    def _validate_identifier(value: str, field: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a string")
        trimmed = value.strip()
        if not _IDENTIFIER_RE.match(trimmed):
            raise ValueError(f"{field} contains unsupported characters")
        return trimmed

    @staticmethod
    def _to_json(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _from_json(value: str) -> Any:
        return json.loads(value or "null")

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "clientSessionId": str(row["client_session_id"]),
            "profileId": str(row["profile_id"]),
            "target": str(row["target"] or ""),
            "scope": str(row["scope"] or ""),
            "createdAt": int(float(row["created_at"]) * 1000),
            "updatedAt": int(float(row["updated_at"]) * 1000),
        }

    def _event_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "eventId": int(row["event_id"]),
            "type": str(row["event_type"]),
            "payload": self._from_json(row["payload_json"]),
            "createdAt": int(float(row["created_at"]) * 1000),
        }

    @staticmethod
    def _grant_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "target": str(row["target"]),
            "workflow": str(row["workflow"]),
            "riskCeiling": str(row["risk_ceiling"]),
            "sourceChannel": str(row["source_channel"]),
            "expiresAt": int(float(row["expires_at"]) * 1000),
        }

    def _job_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "sessionId": str(row["session_id"]),
            "workflow": str(row["workflow"]),
            "target": str(row["target"]),
            "state": str(row["state"]),
            "command": self._from_json(row["command_json"]),
            "reportUrl": str(row["report_url"] or ""),
            "logTail": str(row["log_tail"] or ""),
            "pid": row["pid"],
            "exitCode": row["exit_code"],
            "createdAt": int(float(row["created_at"]) * 1000),
            "updatedAt": int(float(row["updated_at"]) * 1000),
            "startedAt": int(float(row["started_at"]) * 1000) if row["started_at"] else None,
            "finishedAt": int(float(row["finished_at"]) * 1000) if row["finished_at"] else None,
        }
