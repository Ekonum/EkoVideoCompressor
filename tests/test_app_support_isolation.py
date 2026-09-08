"""Guard: the suite must never touch the developer's REAL app-support
directory (``~/Library/Application Support/EkoVideo Compressor``).

Tests exercise code that reaches for ``app_support_dir()`` on its own —
``database()`` in the library helpers, ``append_app_log()`` all over the
engine, ``TranscriptionPipeline._persist_partial_cloud_progress()``. With
the isolation off, those writes land in the user's actual ``library.db``
and ``app.log``: phantom "meeting.mp4" rows with the fixtures' speakers
appear in the app's library, and the log fills with ``error='boom'`` /
``erp.acme.com`` noise — the same log the app exports for support and
that we read to diagnose real incidents.

``tests/__init__.py`` sets the override, but it only runs when the test
modules are imported as part of the ``tests`` *package*. ``python -m
unittest discover -s tests`` (no ``-t``) imports them top-level instead,
silently skipping it — which is exactly how the leak happened.

So this module re-applies the override at *import* time. Discovery
imports test modules in sorted order and this file sorts first among
``test_*.py``, so the override is in place before any other test module
is loaded, whichever way the suite is invoked. The test below then
verifies the invariant actually holds.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from ekovideo_engine.paths import app_support_dir

if not os.environ.get("EKO_APP_SUPPORT_DIR"):
    os.environ["EKO_APP_SUPPORT_DIR"] = tempfile.mkdtemp(prefix="ekovideo-tests-")


class AppSupportIsolationTest(unittest.TestCase):
    def test_override_is_active(self):
        self.assertTrue(
            os.environ.get("EKO_APP_SUPPORT_DIR", "").strip(),
            "EKO_APP_SUPPORT_DIR is unset: the suite would read and write "
            "the real library.db / app.log.",
        )

    def test_resolved_dir_is_not_the_users_own(self):
        # The override could be set to something silly; what actually
        # matters is that nothing resolves into the real app-support dir.
        from pathlib import Path

        real_macos = Path.home() / "Library" / "Application Support" / "EkoVideo Compressor"
        real_linux = Path.home() / ".ekovideocompressor"
        resolved = app_support_dir().resolve()
        for forbidden in (real_macos, real_linux):
            self.assertNotEqual(
                resolved,
                forbidden.resolve() if forbidden.exists() else forbidden,
                f"tests resolve app_support_dir() to {resolved} — the "
                "developer's real data directory.",
            )
