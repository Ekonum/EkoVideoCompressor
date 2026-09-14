"""Schéma et accès SQLite.

Migrations à la main, façon sync-hub : ``CREATE TABLE IF NOT EXISTS``
plus un ``_ensure_column`` idempotent. Pas d'ORM — les requêtes sont
peu nombreuses et le VPS est à 256 Mo.

Écarts assumés par rapport à la base de l'app macOS : ``jobs`` gagne un
``owner_id``, ``source_path`` devient un simple nom de fichier (le
serveur ne voit jamais le média), et ``speaker_profiles`` disparaît avec
pyannote.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id             INTEGER NOT NULL REFERENCES users(id),
    filename             TEXT NOT NULL,
    duration_seconds     REAL NOT NULL DEFAULT 0,
    model                TEXT NOT NULL,
    language             TEXT NOT NULL DEFAULT 'fr',
    status               TEXT NOT NULL DEFAULT 'en_attente',
    error_message        TEXT,
    chunk_count          INTEGER NOT NULL DEFAULT 1,
    context_json         TEXT,
    title                TEXT,
    transcript           TEXT,
    speaker_map_json     TEXT,
    technical_terms_json TEXT,
    cloud_cost_usd       REAL NOT NULL DEFAULT 0,
    compressed_bytes     INTEGER,
    created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_owner ON jobs(owner_id, id DESC);

CREATE TABLE IF NOT EXISTS job_chunks (
    job_id       INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    idx          INTEGER NOT NULL,
    start_second REAL NOT NULL,
    end_second   REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'attendu',
    error        TEXT,
    result_json  TEXT,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (job_id, idx)
);

CREATE TABLE IF NOT EXISTS transcription_segments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    start_second REAL NOT NULL,
    end_second   REAL NOT NULL,
    speaker      TEXT,
    text         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_segments_job ON transcription_segments(job_id, start_second);

CREATE TABLE IF NOT EXISTS api_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    step          TEXT NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_usage_created ON api_usage(created_at);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._conn()
        with conn:
            yield conn

    # -- utilisateurs --------------------------------------------------

    def user_id_for_email(self, email: str) -> int:
        """Crée l'utilisateur à la volée : Access a déjà fait le tri."""
        normalized = email.strip().lower()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE email = ?", (normalized,)
            ).fetchone()
            if row:
                return int(row["id"])
            cursor = conn.execute("INSERT INTO users (email) VALUES (?)", (normalized,))
            return int(cursor.lastrowid)

    # -- jobs ----------------------------------------------------------

    def create_job(
        self,
        *,
        owner_id: int,
        filename: str,
        duration_seconds: float,
        model: str,
        language: str,
        context: dict[str, Any],
        chunks: list[tuple[float, float]],
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO jobs (owner_id, filename, duration_seconds, model, "
                "language, chunk_count, context_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    owner_id,
                    filename,
                    float(duration_seconds),
                    model,
                    language,
                    len(chunks),
                    json.dumps(context, ensure_ascii=False),
                ),
            )
            job_id = int(cursor.lastrowid)
            conn.executemany(
                "INSERT INTO job_chunks (job_id, idx, start_second, end_second) "
                "VALUES (?, ?, ?, ?)",
                [(job_id, i, start, end) for i, (start, end) in enumerate(chunks)],
            )
            return job_id

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def list_jobs(self, owner_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE owner_id = ? ORDER BY id DESC LIMIT ?",
                (owner_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def set_job_status(
        self, job_id: int, status: str, *, error: str | None = None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, error_message = ?, updated_at = ? "
                "WHERE id = ?",
                (status, error, datetime.now().isoformat(timespec="seconds"), job_id),
            )

    def finish_job(
        self,
        job_id: int,
        *,
        title: str,
        transcript: str,
        speakers: dict[str, str],
        technical_terms: list[str],
        cost_usd: float,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'termine', title = ?, transcript = ?, "
                "speaker_map_json = ?, technical_terms_json = ?, cloud_cost_usd = ?, "
                "error_message = NULL, updated_at = ? WHERE id = ?",
                (
                    title,
                    transcript,
                    json.dumps(speakers, ensure_ascii=False),
                    json.dumps(technical_terms, ensure_ascii=False),
                    float(cost_usd),
                    datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )

    # -- segments (fenêtres) -------------------------------------------

    def chunks_for_job(self, job_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM job_chunks WHERE job_id = ? ORDER BY idx", (job_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def set_chunk_status(
        self,
        job_id: int,
        idx: int,
        status: str,
        *,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE job_chunks SET status = ?, error = ?, result_json = "
                "COALESCE(?, result_json), updated_at = ? WHERE job_id = ? AND idx = ?",
                (
                    status,
                    error,
                    json.dumps(result, ensure_ascii=False) if result else None,
                    datetime.now().isoformat(timespec="seconds"),
                    job_id,
                    idx,
                ),
            )

    def replace_segments(self, job_id: int, segments: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM transcription_segments WHERE job_id = ?", (job_id,))
            conn.executemany(
                "INSERT INTO transcription_segments (job_id, start_second, "
                "end_second, speaker, text) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        job_id,
                        float(s.get("start") or 0.0),
                        float(s.get("end") or 0.0),
                        str(s.get("speaker") or ""),
                        str(s.get("text") or ""),
                    )
                    for s in segments
                ],
            )

    def segments_for_job(self, job_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT start_second, end_second, speaker, text FROM "
                "transcription_segments WHERE job_id = ? ORDER BY start_second",
                (job_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- dépenses ------------------------------------------------------

    def add_api_usage(
        self,
        *,
        job_id: int | None,
        provider: str,
        model: str,
        step: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO api_usage (job_id, provider, model, step, "
                "input_tokens, output_tokens, cost_usd) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    provider,
                    model,
                    step,
                    int(input_tokens),
                    int(output_tokens),
                    float(cost_usd),
                ),
            )

    def month_spend_usd(self, month: str | None = None) -> float:
        """Dépense du mois — plafond d'équipe, la clé Gemini étant partagée."""
        period = (month or datetime.now().strftime("%Y-%m")).strip()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM api_usage "
                "WHERE strftime('%Y-%m', created_at) = ?",
                (period,),
            ).fetchone()
            return float(row["total"] if row else 0.0)
