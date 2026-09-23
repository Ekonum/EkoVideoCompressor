"""Bridge to transcript.ekonum.fr: enrol this Mac, then push the library.

The web app is where transcriptions are meant to live from now on. This
module lets the macOS app hand over its history without anyone copying a
token around:

1. ``open_enrolment`` asks the server for a device code (secret, kept by
   the app) and a short human code (shown to the user).
2. The user opens the link in a browser — already authenticated by
   Cloudflare Access — and approves *this* device.
3. ``poll_enrolment`` returns the device's own API token, exactly once.
   The Swift shell stores it in the Keychain, never in a file.
4. ``push_library`` replays every finished meeting through the public
   import endpoint. The server de-duplicates on (owner, filename,
   created_at), so pushing twice is harmless and a rerun after a network
   hiccup simply resumes.

Secrets never travel as command-line arguments (``ps`` would show them to
any local process); the CLI reads them from the environment instead —
the same rule sync-hub follows for its device tokens.

Pure ``urllib`` + ``certifi``, like every other HTTP call in the engine:
no new dependency for the PyInstaller bundle.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    import certifi
except ImportError:  # pragma: no cover - certifi ships with the bundle
    certifi = None  # type: ignore[assignment]

DEFAULT_SERVER = "https://transcript.ekonum.fr"
USER_AGENT = "EkoVideoCompressor/transcript-sync"
TIMEOUT = 60


class TranscriptSyncError(RuntimeError):
    """User-facing failure (French message) with a stable machine code."""

    def __init__(self, message: str, code: str = "transcript_sync") -> None:
        super().__init__(message)
        self.code = code


def _ssl_context() -> ssl.SSLContext:
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def _request(
    method: str,
    url: str,
    *,
    payload: dict | None = None,
    token: str = "",
    opener: Callable[..., Any] | None = None,
) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    open_ = opener or (lambda req, timeout: urllib.request.urlopen(
        req, timeout=timeout, context=_ssl_context()))
    try:
        with open_(request, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8") or "{}").get("detail") or ""
        except (ValueError, AttributeError):
            pass
        if exc.code == 404 and url.rstrip("/").endswith("/api/enroll/device"):
            raise TranscriptSyncError(
                "Le transfert vers transcript.ekonum.fr n'est pas encore ouvert.",
                code="transcript_disabled",
            ) from exc
        if exc.code in (401, 403):
            raise TranscriptSyncError(
                "Accès refusé par transcript.ekonum.fr — relance l'autorisation "
                "de cet appareil.",
                code="transcript_auth",
            ) from exc
        raise TranscriptSyncError(
            detail or f"transcript.ekonum.fr a répondu HTTP {exc.code}.",
            code="transcript_http",
        ) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TranscriptSyncError(
            f"transcript.ekonum.fr est injoignable : {reason}.",
            code="transcript_network",
        ) from exc
    try:
        return json.loads(raw or "{}")
    except ValueError as exc:
        # An HTML page here almost always means Cloudflare Access answered
        # instead of the app — i.e. the machine paths are not opened yet.
        raise TranscriptSyncError(
            "Réponse inattendue de transcript.ekonum.fr (page de connexion ?).",
            code="transcript_unexpected",
        ) from exc


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------


def open_enrolment(
    server: str, device_name: str, *, opener: Callable[..., Any] | None = None
) -> dict:
    """Start an enrolment. Returns ``{code_appareil, code_humain, url,
    expire_le}`` — the first one is a secret the caller must keep."""
    return _request(
        "POST",
        f"{server.rstrip('/')}/api/enroll/device",
        payload={"appareil": (device_name or "").strip()[:120]},
        opener=opener,
    )


def poll_enrolment(
    server: str, device_code: str, *, opener: Callable[..., Any] | None = None
) -> dict:
    """Ask whether the user has approved yet.

    ``statut`` is ``en_attente`` until then, ``approuve`` exactly once
    (with ``token`` and ``email``), and ``consomme`` / ``expire`` after.
    """
    if not device_code:
        raise TranscriptSyncError("Code appareil manquant.", code="transcript_usage")
    return _request(
        "POST",
        f"{server.rstrip('/')}/api/enroll/token",
        payload={"code_appareil": device_code},
        opener=opener,
    )


# ---------------------------------------------------------------------------
# Library push
# ---------------------------------------------------------------------------


def _best_transcript(job: sqlite3.Row) -> str:
    """The most polished transcript on disk.

    Order matters: ``review_path`` is *not* a transcript but the list of
    passages to double-check — a few hundred bytes where the transcript
    weighs tens of thousands.
    """
    for column in ("enhanced_transcript_path", "transcript_path"):
        raw = job[column] if column in job.keys() else None
        if not raw:
            continue
        path = Path(raw)
        if path.exists():
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return ""


def import_payloads(db_path: Path) -> Iterator[dict]:
    """One import payload per meeting that has something to hand over.

    The library is opened **read-only**: a transfer must never be able to
    damage the original.
    """
    source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        for job in source.execute("SELECT * FROM jobs ORDER BY id").fetchall():
            transcript = _best_transcript(job)
            segments = [
                {
                    "start": row["start_time"],
                    "end": row["end_time"],
                    "speaker": row["speaker"] or "",
                    "text": row["text"] or "",
                }
                for row in source.execute(
                    "SELECT * FROM transcription_segments WHERE job_id = ? "
                    "ORDER BY start_time",
                    (job["id"],),
                )
            ]
            if not transcript and not segments:
                # Compression-only job, or artefacts deleted: an empty row
                # on the server would be worse than none.
                continue
            yield {
                "filename": Path(job["source_path"] or "").name or f"job-{job['id']}",
                "created_at": job["created_at"],
                "title": job["custom_title"] or "",
                "duration_seconds": max(
                    (float(s["end"] or 0) for s in segments), default=0.0
                ),
                "model": job["cloud_model"] or job["transcription_model"] or "",
                "transcript": transcript,
                "speakers": json.loads(job["speaker_map_json"] or "{}"),
                "technical_terms": json.loads(job["technical_terms_json"] or "[]"),
                "cost_usd": float(job["cloud_cost_usd"] or 0),
                "segments": segments,
            }
    finally:
        source.close()


def push_library(
    server: str,
    token: str,
    db_path: Path,
    *,
    on_progress: Callable[[int, int, str], None] | None = None,
    opener: Callable[..., Any] | None = None,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Push every meeting; return ``{pushed, already, failed, total}``.

    A network hiccup on one meeting is retried, then counted as failed —
    it never aborts the whole transfer, which would force starting over.
    An authentication failure does abort: every following call would
    fail the same way.
    """
    if not token:
        raise TranscriptSyncError("Aucun accès à transcript.ekonum.fr.", code="transcript_auth")
    if not db_path.exists():
        raise TranscriptSyncError(
            f"Bibliothèque introuvable : {db_path}", code="transcript_usage"
        )
    payloads = list(import_payloads(db_path))
    url = f"{server.rstrip('/')}/api/jobs/import"
    pushed = already = failed = 0
    for index, payload in enumerate(payloads, start=1):
        for attempt in range(retries):
            try:
                answer = _request("POST", url, payload=payload, token=token, opener=opener)
                if answer.get("imported"):
                    pushed += 1
                else:
                    already += 1
                break
            except TranscriptSyncError as exc:
                if exc.code == "transcript_auth":
                    raise
                if exc.code != "transcript_network" or attempt == retries - 1:
                    failed += 1
                    break
                sleep(2 * (attempt + 1))
        if on_progress:
            on_progress(index, len(payloads), payload.get("title") or payload["filename"])
    return {"pushed": pushed, "already": already, "failed": failed, "total": len(payloads)}
