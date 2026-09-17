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

import hashlib
import json
import re
import secrets
import sqlite3
import unicodedata
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
    previous_versions_json TEXT,
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

-- Jetons d'API, pour les appels machine : un script, une intégration
-- Odoo, un serveur MCP. Seule l'empreinte est stockée — un vol de base
-- ne doit pas rendre les jetons utilisables, et personne (pas même
-- l'interface) ne peut réafficher un jeton après sa création.
CREATE TABLE IF NOT EXISTS api_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id     INTEGER NOT NULL REFERENCES users(id),
    name         TEXT NOT NULL,
    token_sha256 TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT,
    revoked_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_tokens_owner ON api_tokens(owner_id, id DESC);

-- Vocabulaire métier, **partagé par toute l'équipe** : « Odoo »,
-- « Ekonum » et les noms de clients sont communs. C'est un gain net sur
-- l'app macOS, où le glossaire était cloisonné par machine.
CREATE TABLE IF NOT EXISTS vocabulary (
    term       TEXT PRIMARY KEY,
    usages     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used  TEXT
);

-- Co-occurrences, stockées dans les deux sens comme le fait l'app macOS.
-- C'est ce qui fait remonter « CVR Contrôle » dès qu'on saisit
-- « Acritec », alors que CVR est globalement plus rare que Odoo ou
-- Ekonum : la suggestion place la co-occurrence avant l'usage brut.
CREATE TABLE IF NOT EXISTS vocabulary_pairs (
    term  TEXT NOT NULL,
    peer  TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (term, peer)
);

-- Recherche plein texte. Table FTS5 autonome plutôt qu'en contenu
-- externe : les segments sont réécrits en bloc à chaque finalisation,
-- et des déclencheurs sur un DELETE massif coûteraient plus qu'ils ne
-- rapportent. Les colonnes UNINDEXED évitent qu'un identifiant de job
-- ressorte comme un résultat de recherche.
CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text,
    job_id       UNINDEXED,
    start_second UNINDEXED,
    speaker      UNINDEXED
);
"""


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn) -> None:
        """Migrations additives, jouées à chaque démarrage.

        La base de production porte déjà l'historique repris : les
        nouvelles colonnes s'ajoutent, la table ne se recrée pas.
        """
        for colonne, ddl in (
            ("odoo_model", "TEXT"),
            ("odoo_record_id", "INTEGER"),
            ("odoo_message_id", "INTEGER"),
            ("odoo_published_at", "TEXT"),
        ):
            self._ensure_column(conn, "jobs", colonne, ddl)

    def _ensure_column(self, conn, table: str, column: str, ddl: str) -> None:
        """Ajout de colonne idempotent — le pendant du helper de sync-hub.

        SQLite n'a pas d'``ADD COLUMN IF NOT EXISTS`` : on lit le schéma
        courant plutôt que d'avaler une exception, qui masquerait une
        vraie erreur de DDL."""
        existing = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

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

    def email_for_user(self, owner_id: int) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT email FROM users WHERE id = ?", (owner_id,)
            ).fetchone()
            return str(row["email"]) if row else ""

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

    def import_job(self, *, owner_id: int, payload: dict[str, Any]) -> tuple[int, bool]:
        """Reprend une réunion déjà transcrite ailleurs.

        Idempotent sur (propriétaire, nom de fichier, date de création) :
        une reprise de plusieurs années de bibliothèque ne réussit jamais
        du premier coup, il faut pouvoir relancer sans doubler.
        """
        nom = str(payload.get("filename") or "").strip() or "sans nom"
        cree = str(payload.get("created_at") or "").strip() or datetime.now().isoformat(timespec="seconds")

        with self.connect() as conn:
            existant = conn.execute(
                "SELECT id FROM jobs WHERE owner_id = ? AND filename = ? AND created_at = ?",
                (owner_id, nom, cree),
            ).fetchone()
            if existant:
                return int(existant["id"]), False

            cursor = conn.execute(
                "INSERT INTO jobs (owner_id, filename, duration_seconds, model, "
                "language, status, chunk_count, context_json, title, transcript, "
                "speaker_map_json, technical_terms_json, cloud_cost_usd, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'fr', 'termine', 1, '{}', ?, ?, ?, ?, ?, ?, ?)",
                (
                    owner_id,
                    nom,
                    float(payload.get("duration_seconds") or 0),
                    str(payload.get("model") or ""),
                    str(payload.get("title") or ""),
                    str(payload.get("transcript") or ""),
                    json.dumps(payload.get("speakers") or {}, ensure_ascii=False),
                    json.dumps(payload.get("technical_terms") or [], ensure_ascii=False),
                    float(payload.get("cost_usd") or 0),
                    cree,
                    cree,
                ),
            )
            job_id = int(cursor.lastrowid)

        segments = payload.get("segments") or []
        if segments:
            self.replace_segments(job_id, segments)
        termes = payload.get("technical_terms") or []
        if termes:
            # Le vocabulaire d'équipe hérite de tout l'historique : à la
            # bascule, les suggestions ne partent pas de zéro.
            self.record_vocabulary([str(t) for t in termes])
        return job_id, True

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
        rows = [
            (
                job_id,
                float(s.get("start") or 0.0),
                float(s.get("end") or 0.0),
                str(s.get("speaker") or ""),
                str(s.get("text") or ""),
            )
            for s in segments
        ]
        with self.connect() as conn:
            conn.execute("DELETE FROM transcription_segments WHERE job_id = ?", (job_id,))
            conn.executemany(
                "INSERT INTO transcription_segments (job_id, start_second, "
                "end_second, speaker, text) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            # L'index plein texte suit dans la même transaction : une
            # recherche ne doit jamais ramener une phrase qui n'existe plus.
            conn.execute("DELETE FROM segments_fts WHERE job_id = ?", (job_id,))
            conn.executemany(
                "INSERT INTO segments_fts (text, job_id, start_second, speaker) "
                "VALUES (?, ?, ?, ?)",
                [(text, job_id, start, speaker) for _, start, _, speaker, text in rows],
            )

    def segments_for_job(self, job_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT start_second, end_second, speaker, text FROM "
                "transcription_segments WHERE job_id = ? ORDER BY start_second",
                (job_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def reset_chunk(self, job_id: int, idx: int) -> None:
        """Remet une fenêtre à l'état attendu pour que le navigateur la
        réencode. C'est le mécanisme derrière « relancer cette fenêtre » :
        sur une réunion de huit fenêtres dont trois ont échoué, rien ne
        justifie de repayer les cinq qui sont passées."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE job_chunks SET status = 'attendu', error = NULL, "
                "result_json = NULL, updated_at = ? WHERE job_id = ? AND idx = ?",
                (datetime.now().isoformat(timespec="seconds"), job_id, idx),
            )

    def archive_current_version(self, job_id: int) -> None:
        """Empile la transcription en place dans l'historique avant qu'une
        relance ne l'écrase. Sans cela, relancer une réunion pour corriger
        une fenêtre détruirait le travail déjà validé dessus."""
        job = self.get_job(job_id)
        if not job or not (job.get("transcript") or "").strip():
            return
        versions = json.loads(job.get("previous_versions_json") or "[]")
        versions.insert(
            0,
            {
                "archived_at": datetime.now().isoformat(timespec="seconds"),
                "title": job.get("title") or "",
                "transcript": job.get("transcript") or "",
                "speaker_map_json": job.get("speaker_map_json"),
                "technical_terms_json": job.get("technical_terms_json"),
                "cloud_cost_usd": job.get("cloud_cost_usd") or 0.0,
            },
        )
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET previous_versions_json = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(versions[:10], ensure_ascii=False),
                    datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )

    def update_job_context(
        self,
        job_id: int,
        *,
        title: str | None = None,
        speakers: dict[str, str] | None = None,
        technical_terms: list[str] | None = None,
    ) -> None:
        """Édition de la fiche par l'utilisateur. Chaque champ absent est
        laissé tel quel — un formulaire partiel ne doit pas effacer ce
        qu'il n'affichait pas."""
        sets: list[str] = []
        values: list[Any] = []
        if title is not None:
            sets.append("title = ?")
            values.append(title.strip())
        if speakers is not None:
            sets.append("speaker_map_json = ?")
            values.append(json.dumps(speakers, ensure_ascii=False))
        if technical_terms is not None:
            sets.append("technical_terms_json = ?")
            values.append(json.dumps(technical_terms, ensure_ascii=False))
        if not sets:
            return
        sets.append("updated_at = ?")
        values.extend([datetime.now().isoformat(timespec="seconds"), job_id])
        with self.connect() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", values)

    def set_transcript(self, job_id: int, transcript: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET transcript = ?, updated_at = ? WHERE id = ?",
                (transcript, datetime.now().isoformat(timespec="seconds"), job_id),
            )

    def search_segments(
        self, owner_id: int, query: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Recherche plein texte dans les transcriptions de l'utilisateur.

        La requête est découpée en termes, chacun cité, pour qu'une
        apostrophe ou un tiret ne soit pas lu comme de la syntaxe FTS —
        « l'équipe » ferait sinon une erreur d'analyse plutôt qu'une
        recherche.
        """
        terms = [t for t in re.split(r"\s+", (query or "").strip()) if t]
        if not terms:
            return []
        match = " ".join('"' + t.replace('"', '""') + '"' for t in terms)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT f.job_id, f.start_second, f.speaker, f.text, "
                "       j.title, j.filename "
                "FROM segments_fts f JOIN jobs j ON j.id = f.job_id "
                "WHERE segments_fts MATCH ? AND j.owner_id = ? "
                "ORDER BY rank LIMIT ?",
                (match, owner_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def set_odoo_link(
        self, job_id: int, *, model: str, record_id: int, message_id: int | None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET odoo_model = ?, odoo_record_id = ?, "
                "odoo_message_id = ?, odoo_published_at = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    model,
                    record_id,
                    message_id,
                    datetime.now().isoformat(timespec="seconds") if message_id else None,
                    datetime.now().isoformat(timespec="seconds"),
                    job_id,
                ),
            )

    # -- jetons d'API ---------------------------------------------------

    def create_api_token(self, owner_id: int, name: str) -> tuple[int, str]:
        """Fabrique un jeton et n'en garde que l'empreinte.

        Renvoie ``(id, jeton en clair)`` — la seule fois où la valeur
        existe. L'appelant doit la montrer puis l'oublier.
        """
        secret = "ekt_" + secrets.token_urlsafe(32)
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO api_tokens (owner_id, name, token_sha256) "
                "VALUES (?, ?, ?)",
                (owner_id, (name or "").strip() or "sans nom", _digest(secret)),
            )
            return int(cursor.lastrowid), secret

    def owner_for_api_token(self, secret: str) -> int | None:
        """Propriétaire d'un jeton valide, ou None.

        La recherche se fait sur l'empreinte : le jeton en clair ne
        touche jamais la base, et l'index porte donc sur une valeur de
        longueur fixe, insensible au contenu du jeton.
        """
        raw = (secret or "").strip()
        if not raw:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, owner_id FROM api_tokens "
                "WHERE token_sha256 = ? AND revoked_at IS NULL",
                (_digest(raw),),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE api_tokens SET last_used_at = ? WHERE id = ?",
                (datetime.now().isoformat(timespec="seconds"), row["id"]),
            )
            return int(row["owner_id"])

    def list_api_tokens(self, owner_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, created_at, last_used_at, revoked_at "
                "FROM api_tokens WHERE owner_id = ? ORDER BY id DESC",
                (owner_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def revoke_api_token(self, owner_id: int, token_id: int) -> bool:
        """Révoque sans supprimer : la ligne garde la trace du dernier
        usage, qui est précisément ce qu'on veut consulter après coup."""
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE api_tokens SET revoked_at = ? "
                "WHERE id = ? AND owner_id = ? AND revoked_at IS NULL",
                (datetime.now().isoformat(timespec="seconds"), token_id, owner_id),
            )
            return cursor.rowcount > 0

    # -- vocabulaire ---------------------------------------------------

    def record_vocabulary(self, terms: list[str]) -> None:
        """Enregistre les termes d'un traitement : usage + appariements.

        Les paires sont écrites symétriquement, pour qu'une suggestion
        fonctionne quel que soit le terme saisi en premier.
        """
        propres = []
        vus: set[str] = set()
        for brut in terms:
            terme = unicodedata.normalize("NFC", str(brut or "").strip())
            cle = terme.lower()
            if terme and cle not in vus:
                vus.add(cle)
                propres.append(terme)
        if not propres:
            return

        maintenant = datetime.now().isoformat(timespec="seconds")
        with self.connect() as conn:
            for terme in propres:
                conn.execute(
                    "INSERT INTO vocabulary (term, usages, last_used) VALUES (?, 1, ?) "
                    "ON CONFLICT(term) DO UPDATE SET usages = usages + 1, last_used = ?",
                    (terme, maintenant, maintenant),
                )
            for terme in propres:
                for pair in propres:
                    if terme == pair:
                        continue
                    conn.execute(
                        "INSERT INTO vocabulary_pairs (term, peer, count) VALUES (?, ?, 1) "
                        "ON CONFLICT(term, peer) DO UPDATE SET count = count + 1",
                        (terme, pair),
                    )

    def suggest_vocabulary(
        self, selected: list[str], limit: int = 30
    ) -> list[dict[str, Any]]:
        """Termes à proposer, les plus pertinents d'abord.

        Le tri place la **co-occurrence avant l'usage brut** : c'est ce
        qui fait remonter un terme rare mais lié à ce qui est déjà
        sélectionné, plutôt que les mêmes cinq termes omniprésents à
        chaque réunion.
        """
        deja = {unicodedata.normalize("NFC", t.strip()).lower() for t in selected if t.strip()}
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT v.term, v.usages, COALESCE(SUM(p.count), 0) AS affinite "
                "FROM vocabulary v "
                "LEFT JOIN vocabulary_pairs p "
                "  ON p.term = v.term AND LOWER(p.peer) IN "
                f"     ({','.join('?' * len(deja)) or 'NULL'}) "
                "GROUP BY v.term "
                "ORDER BY affinite DESC, v.usages DESC, v.term COLLATE NOCASE",
                tuple(deja),
            ).fetchall()
        return [
            {"term": r["term"], "usages": r["usages"], "affinity": r["affinite"]}
            for r in rows
            if r["term"].lower() not in deja
        ][:limit]

    def forget_vocabulary(self, term: str) -> None:
        cible = unicodedata.normalize("NFC", str(term or "").strip())
        with self.connect() as conn:
            conn.execute("DELETE FROM vocabulary WHERE term = ?", (cible,))
            conn.execute(
                "DELETE FROM vocabulary_pairs WHERE term = ? OR peer = ?", (cible, cible)
            )

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
