"""Hand-over of the macOS library to transcript.ekonum.fr.

The HTTP layer is faked at the ``opener`` level — the same seam the
engine uses everywhere — so these tests exercise the real request
building, error mapping and retry policy.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path

from ekovideo_engine.transcript_sync import (
    TranscriptSyncError,
    import_payloads,
    open_enrolment,
    poll_enrolment,
    push_library,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeServer:
    """Records requests and replays scripted answers (or exceptions)."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests: list[dict] = []

    def __call__(self, request, timeout=None):
        self.requests.append({
            "url": request.full_url,
            "method": request.get_method(),
            "headers": {k.lower(): v for k, v in request.header_items()},
            "body": json.loads(request.data.decode()) if request.data else None,
        })
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return _Response(json.dumps(answer).encode())


def _http_error(url: str, code: int, detail: str = "") -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({"detail": detail}).encode())
    return urllib.error.HTTPError(url, code, "err", {}, body)


def _library(root: Path, jobs: list[dict]) -> Path:
    """A minimal library.db with the columns the push reads."""
    db = root / "library.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY, source_path TEXT, created_at TEXT,
            custom_title TEXT, cloud_model TEXT, transcription_model TEXT,
            speaker_map_json TEXT, technical_terms_json TEXT,
            cloud_cost_usd REAL, transcript_path TEXT,
            enhanced_transcript_path TEXT, review_path TEXT, meeting_date TEXT
        );
        CREATE TABLE transcription_segments (
            id INTEGER PRIMARY KEY, job_id INTEGER, start_time REAL,
            end_time REAL, speaker TEXT, text TEXT
        );
        """
    )
    for job in jobs:
        conn.execute(
            "INSERT INTO jobs (id, source_path, created_at, custom_title, "
            "cloud_model, speaker_map_json, technical_terms_json, cloud_cost_usd, "
            "transcript_path, review_path, meeting_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (job["id"], job.get("source", f"/tmp/reunion{job['id']}.mov"),
             job.get("created_at", "2026-09-04 11:54:50"), job.get("title", ""),
             "gemini-3.8-flash", "{}", "[]", 0.36,
             job.get("transcript_path"), job.get("review_path"), job.get("meeting_date")),
        )
        for i, text in enumerate(job.get("segments", [])):
            conn.execute(
                "INSERT INTO transcription_segments (job_id, start_time, end_time, "
                "speaker, text) VALUES (?,?,?,?,?)",
                (job["id"], i * 5.0, i * 5.0 + 4.0, "Robin", text),
            )
    conn.commit()
    conn.close()
    return db


class EnrolmentTest(unittest.TestCase):
    def test_open_sends_the_device_name_and_returns_both_codes(self):
        server = FakeServer([{"code_appareil": "ekd_secret", "code_humain": "ABCD-2345",
                              "url": "https://t/?code=ABCD-2345", "expire_le": "x"}])
        answer = open_enrolment("https://t", "MacBook de Robin", opener=server)
        self.assertEqual(answer["code_humain"], "ABCD-2345")
        self.assertEqual(server.requests[0]["url"], "https://t/api/enroll/device")
        self.assertEqual(server.requests[0]["body"], {"appareil": "MacBook de Robin"})

    def test_a_disabled_server_says_so_in_plain_french(self):
        server = FakeServer([_http_error("https://t/api/enroll/device", 404)])
        with self.assertRaises(TranscriptSyncError) as ctx:
            open_enrolment("https://t", "Mac", opener=server)
        self.assertEqual(ctx.exception.code, "transcript_disabled")
        self.assertIn("pas encore ouvert", str(ctx.exception))

    def test_an_access_login_page_is_named_not_swallowed(self):
        """Cloudflare Access answering instead of the app returns HTML —
        the first thing to check when enrolment silently fails."""
        class Html(FakeServer):
            def __call__(self, request, timeout=None):
                return _Response(b"<html>Sign in</html>")

        with self.assertRaises(TranscriptSyncError) as ctx:
            open_enrolment("https://t", "Mac", opener=Html([]))
        self.assertEqual(ctx.exception.code, "transcript_unexpected")

    def test_poll_carries_the_device_code_in_the_body_only(self):
        server = FakeServer([{"statut": "en_attente"}])
        answer = poll_enrolment("https://t", "ekd_secret", opener=server)
        self.assertEqual(answer["statut"], "en_attente")
        self.assertEqual(server.requests[0]["body"], {"code_appareil": "ekd_secret"})
        self.assertNotIn("ekd_secret", server.requests[0]["url"])

    def test_poll_without_a_code_fails_before_any_call(self):
        server = FakeServer([])
        with self.assertRaises(TranscriptSyncError):
            poll_enrolment("https://t", "", opener=server)
        self.assertEqual(server.requests, [])


class PushTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        transcript = self.root / "acritec.txt"
        transcript.write_text("Robin : on migre vers Odoo 19.", encoding="utf-8")
        review = self.root / "acritec - à vérifier.md"
        review.write_text("2 passages douteux", encoding="utf-8")
        self.db = _library(self.root, [
            {"id": 1, "title": "Acritec - Revue", "transcript_path": str(transcript),
             "review_path": str(review), "segments": ["on migre", "vers Odoo"],
             "meeting_date": "2026-09-04T07:00:00Z"},
            {"id": 2, "title": "Compression seule"},  # nothing to hand over
            {"id": 3, "title": "PassPassion", "segments": ["démo VoIP"]},
        ])

    def tearDown(self):
        self._tmp.cleanup()

    def test_only_meetings_with_content_are_pushed(self):
        payloads = list(import_payloads(self.db))
        self.assertEqual([p["title"] for p in payloads], ["Acritec - Revue", "PassPassion"])

    def test_the_transcript_is_never_the_review_file(self):
        """The review file lists doubtful passages; pushing it as the
        transcript lost 114 minutes of text once already."""
        acritec = next(import_payloads(self.db))
        self.assertIn("Odoo 19", acritec["transcript"])
        self.assertNotIn("douteux", acritec["transcript"])

    def test_the_meeting_date_travels_with_the_transfer(self):
        """Otherwise a transferred library sorts by the day of transfer."""
        payloads = list(import_payloads(self.db))
        self.assertEqual(payloads[0]["meeting_date"], "2026-09-04T07:00:00Z")
        self.assertEqual(payloads[1]["meeting_date"], "")

    def test_the_library_is_opened_read_only(self):
        before = self.db.read_bytes()
        list(import_payloads(self.db))
        self.assertEqual(self.db.read_bytes(), before)

    def test_push_counts_new_and_already_present_meetings(self):
        server = FakeServer([{"imported": True}, {"imported": False}])
        progress: list[tuple[int, int]] = []
        summary = push_library(
            "https://t", "ekt_token", self.db, opener=server,
            on_progress=lambda done, total, _label: progress.append((done, total)),
        )
        self.assertEqual(summary, {"pushed": 1, "already": 1, "failed": 0, "total": 2})
        self.assertEqual(progress, [(1, 2), (2, 2)])
        self.assertEqual(server.requests[0]["headers"]["authorization"], "Bearer ekt_token")

    def test_a_network_hiccup_is_retried_not_fatal(self):
        server = FakeServer([
            urllib.error.URLError("reset"), {"imported": True}, {"imported": True},
        ])
        summary = push_library("https://t", "ekt", self.db, opener=server,
                               sleep=lambda _s: None)
        self.assertEqual(summary["pushed"], 2)
        self.assertEqual(summary["failed"], 0)

    def test_a_meeting_that_keeps_failing_does_not_stop_the_others(self):
        server = FakeServer([_http_error("https://t/api/jobs/import", 500),
                             {"imported": True}])
        summary = push_library("https://t", "ekt", self.db, opener=server,
                               sleep=lambda _s: None)
        self.assertEqual(summary, {"pushed": 1, "already": 0, "failed": 1, "total": 2})

    def test_a_revoked_token_stops_everything(self):
        """Every following call would fail the same way."""
        server = FakeServer([_http_error("https://t/api/jobs/import", 401)])
        with self.assertRaises(TranscriptSyncError) as ctx:
            push_library("https://t", "ekt", self.db, opener=server)
        self.assertEqual(ctx.exception.code, "transcript_auth")
        self.assertEqual(len(server.requests), 1)

    def test_no_token_no_call(self):
        server = FakeServer([])
        with self.assertRaises(TranscriptSyncError):
            push_library("https://t", "", self.db, opener=server)
        self.assertEqual(server.requests, [])


class CliSecretsTest(unittest.TestCase):
    def test_secrets_are_not_accepted_as_arguments(self):
        """`ps` shows argv to every local process: the device code and
        the token must come from the environment."""
        from ekovideo_engine.cli import build_parser

        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["transcript-push", "--token", "ekt_x"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["transcript-enroll-poll", "--device-code", "ekd_x"])


if __name__ == "__main__":
    unittest.main()
