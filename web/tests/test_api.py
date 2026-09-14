"""Tests de l'API, sans jamais joindre Gemini.

Le fournisseur est remplacé par un double : ce qu'on vérifie ici, c'est
le contrat — plan de découpage autoritatif, garde-fou budget *avant*
l'upload, 202 immédiat, reprise par fenêtres manquantes, cloisonnement
entre utilisateurs.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as _app_package  # noqa: F401  (installe la racine du dépôt dans sys.path)

import tempfile

from fastapi.testclient import TestClient

from app import transcription
from app.db import Database
from app.main import create_app
from app.secrets import GeminiKey
from app.settings import Settings
from cloud_transcription import CloudChunkResult, CloudTranscriptionError, CloudUsage


def _settings(root: Path, **overrides) -> Settings:
    base = dict(
        db_path=root / "test.db",
        chunk_dir=root / "chunks",
        access_team_domain="",
        access_aud="",
        broker_url="http://broker.invalid/v1/secret",
        broker_token="",
        broker_item="Ekonum - API Gemini",
        broker_field="Clé API",
        monthly_budget_usd=50.0,
        dev_mode=True,
        dev_user_email="robin@ekonum.fr",
        dev_api_key="cle-de-test",
    )
    base.update(overrides)
    return Settings(**base)


class FakeResult:
    """Résultat de fenêtre déterministe, indexé pour vérifier la fusion."""

    @staticmethod
    def for_index(index: int) -> CloudChunkResult:
        return CloudChunkResult(
            segments=[
                {
                    "start": 10.0 + index,
                    "end": 20.0 + index,
                    "speaker": "Robin",
                    "text": f"fenêtre {index}",
                }
            ],
            speakers={"Intervenant 1": "Robin"},
            technical_terms=[f"terme{index}"],
            title="Acritec - Revue mensuelle",
            usage=CloudUsage(
                model="gemini-3.8-flash",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.01,
            ),
        )


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.settings = _settings(self.root)
        self.db = Database(self.settings.db_path)
        self.calls: list[tuple[str, int]] = []

        def fake_transcribe(audio_path, *, model_id, context, api_key, **_):
            self.calls.append((api_key, context.chunk_index))
            return FakeResult.for_index(context.chunk_index)

        self._real = transcription.transcribe_chunk
        transcription.transcribe_chunk = fake_transcribe
        import app.main as main_module

        main_module.transcribe_chunk = fake_transcribe

        self.app = create_app(
            self.settings,
            database=self.db,
            gemini_key=GeminiKey(
                url="", token="", item="", field="", static_key="cle-de-test"
            ),
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        transcription.transcribe_chunk = self._real
        self._tmp.cleanup()

    # -- création ------------------------------------------------------

    def _create(self, duration=3600.0, **kwargs) -> dict:
        payload = {
            "filename": "reunion.mov",
            "duration_seconds": duration,
            "model": "gemini-3.8-flash",
            "language": "fr",
            "context": {"client_company": "Acritec"},
        }
        payload.update(kwargs)
        response = self.client.post("/api/jobs", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_le_plan_de_decoupage_vient_du_serveur(self):
        """Le navigateur exécute un plan, il ne le calcule pas."""
        body = self._create(duration=3600.0)
        self.assertEqual(len(body["chunks"]), 2)
        self.assertEqual(body["chunks"][0]["start"], 0.0)
        self.assertEqual(body["chunks"][-1]["end"], 3600.0)
        self.assertEqual(body["audio"]["codec"], "mp3")
        self.assertEqual(body["audio"]["sample_rate"], 16000)

    def test_une_reunion_courte_reste_une_seule_fenetre(self):
        body = self._create(duration=600.0)
        self.assertEqual(len(body["chunks"]), 1)

    def test_modele_inconnu_refuse(self):
        """Le moteur macOS tolère un modèle inconnu (et le facture au tarif
        le plus cher) ; ici la liste est fermée, donc une coquille est
        refusée plutôt que facturée au prix fort."""
        response = self.client.post(
            "/api/jobs",
            json={
                "filename": "x.mov",
                "duration_seconds": 60,
                "model": "modele-qui-nexiste-pas",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_le_garde_fou_budget_bloque_avant_le_premier_octet(self):
        """Le refus doit tomber à la création, pas après un upload."""
        self.db.add_api_usage(
            job_id=None,
            provider="gemini",
            model="gemini-3.8-flash",
            step="cloud_transcription",
            input_tokens=0,
            output_tokens=0,
            cost_usd=49.99,
        )
        response = self.client.post(
            "/api/jobs",
            json={
                "filename": "longue.mov",
                "duration_seconds": 10800,
                "model": "gemini-3.8-flash",
            },
        )
        self.assertEqual(response.status_code, 402)
        self.assertIn("plafond mensuel", response.json()["detail"])

    # -- fenêtres ------------------------------------------------------

    def test_une_fenetre_uploadee_ressort_transcrite(self):
        body = self._create(duration=600.0)
        job_id = body["job_id"]

        response = self.client.put(
            f"/api/jobs/{job_id}/chunks/0", content=b"audio-opus-factice"
        )
        self.assertEqual(response.status_code, 202, response.text)

        state = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(state["chunks"][0]["status"], "termine")
        self.assertEqual(state["missing_chunks"], [])

        final = self.client.post(f"/api/jobs/{job_id}/finalize")
        self.assertEqual(final.status_code, 200, final.text)
        self.assertIn("fenêtre 0", final.json()["transcript"])
        self.assertEqual(final.json()["title"], "Acritec - Revue mensuelle")

    def test_la_cle_du_broker_est_celle_passee_au_fournisseur(self):
        body = self._create(duration=600.0)
        self.client.put(f"/api/jobs/{body['job_id']}/chunks/0", content=b"audio")
        self.assertEqual(self.calls[0][0], "cle-de-test")

    def test_la_fenetre_est_effacee_du_disque_apres_coup(self):
        """Le disque du VPS est tendu : rien ne doit rester derrière."""
        body = self._create(duration=600.0)
        self.client.put(f"/api/jobs/{body['job_id']}/chunks/0", content=b"audio")
        self.assertEqual(list(self.settings.chunk_dir.glob("*.mp3")), [])

    def test_une_fenetre_vide_est_refusee(self):
        body = self._create(duration=600.0)
        response = self.client.put(f"/api/jobs/{body['job_id']}/chunks/0", content=b"")
        self.assertEqual(response.status_code, 400)

    def test_une_fenetre_inconnue_est_refusee(self):
        body = self._create(duration=600.0)
        response = self.client.put(f"/api/jobs/{body['job_id']}/chunks/7", content=b"x")
        self.assertEqual(response.status_code, 404)

    # -- reprise -------------------------------------------------------

    def test_les_fenetres_manquantes_pilotent_la_reprise(self):
        body = self._create(duration=3600.0)
        job_id = body["job_id"]
        self.client.put(f"/api/jobs/{job_id}/chunks/0", content=b"audio")

        state = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(state["missing_chunks"], [1])

        # Tant qu'il manque une fenêtre, on ne finalise pas.
        self.assertEqual(self.client.post(f"/api/jobs/{job_id}/finalize").status_code, 409)

        self.client.put(f"/api/jobs/{job_id}/chunks/1", content=b"audio")
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["missing_chunks"], [])
        final = self.client.post(f"/api/jobs/{job_id}/finalize")
        self.assertEqual(final.status_code, 200, final.text)
        # Les deux fenêtres sont fusionnées, pas la dernière seule.
        self.assertIn("fenêtre 0", final.json()["transcript"])
        self.assertIn("fenêtre 1", final.json()["transcript"])

    def test_un_echec_de_fenetre_est_visible_et_rejouable(self):
        body = self._create(duration=600.0)
        job_id = body["job_id"]

        def failing(*_a, **_k):
            raise CloudTranscriptionError("Gemini indisponible.", code="cloud_api")

        import app.main as main_module

        main_module.transcribe_chunk = failing
        self.client.put(f"/api/jobs/{job_id}/chunks/0", content=b"audio")
        state = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(state["chunks"][0]["status"], "erreur")
        self.assertEqual(state["status"], "erreur")
        self.assertEqual(state["missing_chunks"], [0])

        main_module.transcribe_chunk = lambda *a, **k: FakeResult.for_index(0)
        self.client.put(f"/api/jobs/{job_id}/chunks/0", content=b"audio")
        self.assertEqual(
            self.client.get(f"/api/jobs/{job_id}").json()["chunks"][0]["status"],
            "termine",
        )

    # -- dépenses et cloisonnement -------------------------------------

    def test_la_depense_est_enregistree_par_fenetre(self):
        body = self._create(duration=3600.0)
        job_id = body["job_id"]
        self.client.put(f"/api/jobs/{job_id}/chunks/0", content=b"audio")
        self.client.put(f"/api/jobs/{job_id}/chunks/1", content=b"audio")
        self.assertAlmostEqual(self.db.month_spend_usd(), 0.02, places=6)

    def test_le_job_dun_collegue_est_introuvable(self):
        body = self._create(duration=600.0)
        autre = self.db.user_id_for_email("luka@ekonum.fr")
        self.db.create_job(
            owner_id=autre,
            filename="prive.mov",
            duration_seconds=60,
            model="gemini-3.8-flash",
            language="fr",
            context={},
            chunks=[(0.0, 60.0)],
        )
        # Le job de Robin passe, celui de Lùka renvoie 404 — pas 403, qui
        # révélerait son existence.
        self.assertEqual(self.client.get(f"/api/jobs/{body['job_id']}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{body['job_id'] + 1}").status_code, 404)


class SettingsTestCase(unittest.TestCase):
    def test_refus_de_demarrer_sans_authentification(self):
        """Un déploiement ne doit pas pouvoir s'ouvrir par inadvertance."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = _settings(root, dev_mode=False)
            with self.assertRaises(RuntimeError):
                create_app(settings, database=Database(root / "a.db"))


if __name__ == "__main__":
    unittest.main()
