"""L'avancement d'une transcription : une estimation qui n'annonce
jamais fini ce qui ne l'est pas."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as _app_package  # noqa: F401

from app import avancement
from tests.test_api import _Fixture

MAINTENANT = datetime(2026, 10, 13, 12, 0, 0)


def _fenetre(status, debut=0.0, fin=1800.0, depuis=None):
    return {
        "status": status,
        "start_second": debut,
        "end_second": fin,
        "started_at": (MAINTENANT - timedelta(seconds=depuis)).isoformat()
        if depuis is not None
        else None,
    }


class EstimationTestCase(unittest.TestCase):
    def test_sans_historique_la_mesure_du_13_octobre_sert(self):
        self.assertEqual(avancement.ratio_from_history([(1800, 300)] * 4), avancement.DEFAULT_RATIO)

    def test_l_historique_donne_la_mediane(self):
        # 10 s fixes puis 0,1 s par seconde d'audio ; une fenêtre relancée
        # (très lente) ne déplace pas la médiane.
        echantillons = [(1000, 110)] * 6 + [(1000, 5000)]
        self.assertAlmostEqual(avancement.ratio_from_history(echantillons), 0.1)

    def test_une_fenetre_a_l_heure_prevue_affiche_90_pour_cent(self):
        prevu = avancement.estimated_seconds(1800, 0.1)
        f = _fenetre("en_cours", depuis=prevu)
        self.assertAlmostEqual(avancement.chunk_fraction(f, 0.1, MAINTENANT), 0.9)

    def test_une_fenetre_en_retard_n_atteint_jamais_la_fin(self):
        f = _fenetre("en_cours", depuis=10_000)
        part = avancement.chunk_fraction(f, 0.1, MAINTENANT)
        self.assertGreater(part, 0.9)
        self.assertLess(part, 1.0)

    def test_une_fenetre_qui_attend_son_tour_n_avance_pas(self):
        self.assertEqual(avancement.chunk_fraction(_fenetre("en_cours"), 0.1, MAINTENANT), 0.0)
        self.assertEqual(avancement.chunk_fraction(_fenetre("attendu"), 0.1, MAINTENANT), 0.0)

    def test_la_transcription_est_ponderee_par_la_duree(self):
        fenetres = [
            _fenetre("termine", 0, 1800),
            _fenetre("attendu", 1800, 2400),
        ]
        self.assertAlmostEqual(
            avancement.transcription_fraction(fenetres, 0.1, MAINTENANT), 0.75
        )


class ApiAvancementTestCase(_Fixture):
    def test_la_vue_donne_estimation_et_temps_ecoule(self):
        body = self._create(duration=3600.0)
        job_id = body["job_id"]
        self.client.put(f"/api/jobs/{job_id}/chunks/0", content=b"audio")
        vue = self.client.get(f"/api/jobs/{job_id}").json()
        faite, attendue = vue["chunks"]
        self.assertEqual(faite["status"], "termine")
        self.assertIsNone(faite["elapsed_seconds"])
        self.assertGreater(attendue["estimated_seconds"], avancement.OVERHEAD_SECONDS)
        # Gemini a pris la fenêtre : elle est horodatée pour l'historique.
        (enregistree,) = [c for c in self.db.chunks_for_job(job_id) if c["idx"] == 0]
        self.assertIsNotNone(enregistree["started_at"])

    def test_une_fenetre_relancee_perd_son_horodatage(self):
        body = self._create(duration=600.0)
        job_id = body["job_id"]
        self.client.put(f"/api/jobs/{job_id}/chunks/0", content=b"audio")
        self.db.reset_chunk(job_id, 0)
        (fenetre,) = self.db.chunks_for_job(job_id)
        self.assertIsNone(fenetre["started_at"])


if __name__ == "__main__":
    unittest.main()
