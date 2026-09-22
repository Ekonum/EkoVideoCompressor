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

import json
import tempfile

from fastapi.testclient import TestClient

from app import transcription
from app.coffre import Coffre
from app.db import Database
from app.main import create_app
from app.secrets import GeminiKey
from app.settings import Settings
from cloud_transcription import CloudChunkResult, CloudTranscriptionError, CloudUsage


_CLE_DE_TEST = Coffre.nouvelle_cle()


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
        odoo_url="",
        odoo_database="",
        odoo_login="",
        odoo_broker_item="Ekonum - API Odoo",
        odoo_broker_field="Clé API",
        secret_key=_CLE_DE_TEST,
        monthly_budget_usd=50.0,
        liaison_auto="certaine",
        sonde_ignore=frozenset({"odoo", "ekonum"}),
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


class _Fixture(unittest.TestCase):
    """Montage commun : serveur en mode développement, fournisseur doublé."""

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


class ApiTestCase(_Fixture):
    """Le contrat d'exécution : plan, budget, envoi, reprise."""

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

class OdooMessageLisibleTest(unittest.TestCase):
    def test_une_base_inconnue_se_dit_en_une_phrase(self):
        from app.odoo import _lisible
        from odoo_client import OdooError

        page = ("Erreur Odoo HTTP 404 : <!DOCTYPE html>\n<title>404 Not Found</title>"
                "<p>No database is selected and the requested URL was not found</p>")
        self.assertEqual(_lisible(OdooError(page), "openerp"),
                         "La base Odoo « openerp » est introuvable sur ce serveur.")

    def test_le_html_est_retire_et_le_message_borne(self):
        from app.odoo import _lisible
        from odoo_client import OdooError

        message = _lisible(OdooError("<h1>Erreur</h1> " + "x" * 500), "ekonum")
        self.assertNotIn("<", message)
        self.assertLessEqual(len(message), 240)


class OdooPackDeContexteTest(unittest.TestCase):
    def test_le_pack_passe_par_les_vraies_fonctions_du_client(self):
        """Ce chemin n'était couvert que par une fausse passerelle : un
        appel à la mauvaise signature n'a été vu qu'en production."""
        from unittest import mock

        from app import odoo as module

        pack = {
            "primary": {"display_name": "Acritec",
                        "raw": {"partner_id": [2046, "ACRITEC, David JAUCH"]}},
            "related": [],
            "summary": "Opportunité Acritec : facturation électronique.",
            "terms": ["Acritec", "VISIOTEC"],
        }
        passerelle = module.OdooGateway(url="https://odoo.test", database="ekonum",
                                        login="robin@ekonum.fr", api_key="k")
        with mock.patch.object(module, "fetch_related_context_pack", return_value=pack):
            vue = passerelle.context_pack("crm.lead", 983)
        self.assertEqual(vue["terms"], ["Acritec", "VISIOTEC"])
        self.assertEqual(vue["client_company"], "ACRITEC")
        self.assertIn("facturation", vue["summary"])


class OdooClientSansMoteurTest(unittest.TestCase):
    def test_repli_de_journalisation(self):
        """Le conteneur n'embarque pas ekovideo_engine : le repli de
        journalisation doit accepter exactement les appels du module."""
        import subprocess

        code = (
            "import sys; sys.modules['ekovideo_engine'] = None; "
            "sys.modules['ekovideo_engine.logging'] = None; "
            "import odoo_client as o; "
            "assert o.append_app_log.__module__ == 'odoo_client'; "
            "o.append_app_log('odoo_json2_request host=x'); "
            "assert o.tail_text('abcdef', 3) == '...def'"
        )
        racine = Path(__file__).resolve().parents[2]
        subprocess.run([sys.executable, "-c", code], cwd=racine, check=True)


class LibraryTestCase(_Fixture):
    """Bibliothèque : consultation, édition, recherche, relance."""

    def _finished_job(self, duration=600.0) -> int:
        body = self._create(duration=duration)
        job_id = body["job_id"]
        for chunk in body["chunks"]:
            self.client.put(
                f"/api/jobs/{job_id}/chunks/{chunk['index']}", content=b"audio"
            )
        self.client.post(f"/api/jobs/{job_id}/finalize")
        return job_id

    def test_la_liste_ne_montre_que_ses_propres_traitements(self):
        mine = self._finished_job()
        autre = self.db.user_id_for_email("luka@ekonum.fr")
        self.db.create_job(
            owner_id=autre, filename="prive.mov", duration_seconds=60,
            model="gemini-3.8-flash", language="fr", context={}, chunks=[(0.0, 60.0)],
        )
        listed = self.client.get("/api/jobs").json()
        self.assertEqual([j["job_id"] for j in listed], [mine])

    def test_le_detail_porte_segments_interlocuteurs_et_termes(self):
        job_id = self._finished_job()
        detail = self.client.get(f"/api/jobs/{job_id}/detail").json()
        self.assertEqual(detail["speakers"], {"Intervenant 1": "Robin"})
        self.assertEqual(detail["technical_terms"], ["terme0"])
        self.assertEqual(len(detail["segments"]), 1)
        self.assertEqual(detail["segments"][0]["speaker"], "Robin")

    def test_l_edition_partielle_n_efface_pas_le_reste(self):
        """Un formulaire qui n'affiche pas les termes ne doit pas les perdre."""
        job_id = self._finished_job()
        response = self.client.patch(
            f"/api/jobs/{job_id}", json={"title": "Acritec - Revue de mars"}
        )
        self.assertEqual(response.status_code, 200)
        detail = self.client.get(f"/api/jobs/{job_id}/detail").json()
        self.assertEqual(detail["title"], "Acritec - Revue de mars")
        self.assertEqual(detail["technical_terms"], ["terme0"])

    def test_le_remplacement_de_terme_touche_transcription_segments_et_glossaire(self):
        job_id = self._finished_job()
        self.db.set_transcript(job_id, "Robin : fenêtre 0 chez Acritek.")
        self.db.update_job_context(job_id, technical_terms=["Acritek", "Odoo"])
        self.db.replace_segments(
            job_id,
            [{"start": 0, "end": 5, "speaker": "Robin", "text": "chez Acritek"}],
        )

        response = self.client.post(
            f"/api/jobs/{job_id}/terms/replace", json={"old": "Acritek", "new": "Acritec"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["occurrences"], 2)

        detail = self.client.get(f"/api/jobs/{job_id}/detail").json()
        self.assertIn("Acritec", detail["transcript"])
        self.assertNotIn("Acritek", detail["transcript"])
        self.assertEqual(detail["segments"][0]["text"], "chez Acritec")
        self.assertEqual(detail["technical_terms"], ["Acritec", "Odoo"])

    def test_la_recherche_plein_texte_traverse_les_traitements(self):
        job_id = self._finished_job()
        self.db.replace_segments(
            job_id,
            [
                {"start": 0, "end": 5, "speaker": "Robin", "text": "on migre vers Odoo 19"},
                {"start": 5, "end": 9, "speaker": "Lùka", "text": "rien à signaler"},
            ],
        )
        hits = self.client.get("/api/search", params={"q": "Odoo"}).json()
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["job_id"], job_id)
        self.assertIn("Odoo", hits[0]["text"])

    def test_la_recherche_encaisse_une_apostrophe(self):
        """« l'équipe » ne doit pas partir en erreur de syntaxe FTS."""
        job_id = self._finished_job()
        self.db.replace_segments(
            job_id, [{"start": 0, "end": 5, "speaker": "", "text": "toute l'équipe"}]
        )
        response = self.client.get("/api/search", params={"q": "l'équipe"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)

    def test_la_recherche_ne_ramene_pas_une_phrase_effacee(self):
        job_id = self._finished_job()
        self.db.replace_segments(
            job_id, [{"start": 0, "end": 5, "speaker": "", "text": "budget confidentiel"}]
        )
        self.db.replace_segments(
            job_id, [{"start": 0, "end": 5, "speaker": "", "text": "autre chose"}]
        )
        self.assertEqual(self.client.get("/api/search", params={"q": "confidentiel"}).json(), [])

    def test_la_recherche_ne_traverse_pas_les_utilisateurs(self):
        autre = self.db.user_id_for_email("luka@ekonum.fr")
        job = self.db.create_job(
            owner_id=autre, filename="prive.mov", duration_seconds=60,
            model="gemini-3.8-flash", language="fr", context={}, chunks=[(0.0, 60.0)],
        )
        self.db.replace_segments(
            job, [{"start": 0, "end": 5, "speaker": "", "text": "secret de Lùka"}]
        )
        self.assertEqual(self.client.get("/api/search", params={"q": "secret"}).json(), [])

    def test_relancer_une_fenetre_ne_redemande_que_celle_la(self):
        body = self._create(duration=3600.0)
        job_id = body["job_id"]
        for index in (0, 1):
            self.client.put(f"/api/jobs/{job_id}/chunks/{index}", content=b"audio")
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["missing_chunks"], [])

        self.assertEqual(
            self.client.post(f"/api/jobs/{job_id}/chunks/1/reset").status_code, 200
        )
        self.assertEqual(self.client.get(f"/api/jobs/{job_id}").json()["missing_chunks"], [1])

    def test_une_relance_archive_la_version_precedente(self):
        job_id = self._finished_job()
        self.db.set_transcript(job_id, "première version relue")

        self.client.post(f"/api/jobs/{job_id}/chunks/0/reset")
        self.client.put(f"/api/jobs/{job_id}/chunks/0", content=b"audio")
        self.client.post(f"/api/jobs/{job_id}/finalize")

        detail = self.client.get(f"/api/jobs/{job_id}/detail").json()
        self.assertEqual(len(detail["previous_versions"]), 1)
        self.assertEqual(detail["previous_versions"][0]["transcript"], "première version relue")
        self.assertIn("fenêtre 0", detail["transcript"])


class VocabularyTestCase(_Fixture):
    """Vocabulaire d'équipe : partagé, et trié par affinité."""

    def test_le_vocabulaire_est_enregistre_des_la_creation(self):
        """Dès la création, pas à la fin : une réunion qui échoue doit
        quand même avoir appris ses termes."""
        self._create(context={"glossary_terms": ["Odoo", "EDOF"], "client_company": "Acritec"})
        termes = [t["term"] for t in self.client.get("/api/vocabulary").json()]
        self.assertCountEqual(termes, ["Odoo", "EDOF", "Acritec"])

    def test_la_cooccurrence_passe_avant_l_usage_brut(self):
        """« CVR Contrôle » doit remonter dès qu'on saisit « Acritec »,
        même si Odoo est globalement bien plus fréquent."""
        for _ in range(5):
            self.client.post("/api/vocabulary", json={"terms": ["Odoo", "Ekonum"]})
        self.client.post("/api/vocabulary", json={"terms": ["Acritec", "CVR Contrôle"]})

        suggestions = self.client.get(
            "/api/vocabulary", params={"selected": "Acritec"}
        ).json()
        self.assertEqual(suggestions[0]["term"], "CVR Contrôle")
        # Et sans contexte, c'est bien l'usage qui gouverne.
        sans_contexte = self.client.get("/api/vocabulary").json()
        self.assertIn(sans_contexte[0]["term"], {"Odoo", "Ekonum"})

    def test_les_termes_deja_choisis_ne_sont_pas_resuggeres(self):
        self.client.post("/api/vocabulary", json={"terms": ["Odoo", "Ekonum"]})
        suggestions = self.client.get(
            "/api/vocabulary", params={"selected": "odoo"}
        ).json()
        self.assertNotIn("Odoo", [s["term"] for s in suggestions])

    def test_le_vocabulaire_est_partage_entre_collegues(self):
        """Le cloisonnement par machine de l'app macOS disparaît : c'est
        le gain attendu du passage en webapp."""
        self.client.post("/api/vocabulary", json={"terms": ["Wedophone"]})
        autre = self.db.user_id_for_email("luka@ekonum.fr")
        self.assertGreater(autre, 0)
        self.assertIn("Wedophone", [t["term"] for t in self.db.suggest_vocabulary([])])

    def test_un_terme_peut_etre_oublie(self):
        self.client.post("/api/vocabulary", json={"terms": ["Acritek", "Odoo"]})
        self.assertEqual(self.client.delete("/api/vocabulary/Acritek").status_code, 204)
        self.assertEqual(
            [t["term"] for t in self.client.get("/api/vocabulary").json()], ["Odoo"]
        )

    def test_les_reglages_exposent_modeles_et_budget(self):
        vue = self.client.get("/api/settings").json()
        self.assertTrue(any(m["default"] for m in vue["models"]))
        self.assertEqual(vue["budget"]["cap_usd"], 50.0)
        self.assertEqual(vue["budget"]["spent_usd"], 0.0)


class OdooTestCase(_Fixture):
    """Odoo enrichit, il ne conditionne pas."""

    def test_une_panne_odoo_ne_casse_pas_la_page(self):
        """Odoo absent renvoie une liste vide et une raison — pas une
        erreur. Une réunion doit se transcrire même si Odoo est en
        maintenance."""
        vue = self.client.get("/api/odoo/meetings").json()
        self.assertFalse(vue["available"])
        self.assertEqual(vue["meetings"], [])
        self.assertIn("ton compte", vue["reason"])

    def test_le_pack_de_contexte_refuse_franchement_sans_cle(self):
        """Là en revanche l'appelant a demandé une donnée précise : mieux
        vaut un refus explicite qu'un pack vide qu'il croirait complet."""
        response = self.client.get(
            "/api/odoo/context", params={"model": "crm.lead", "record_id": 1}
        )
        self.assertEqual(response.status_code, 503)

    def test_les_reglages_disent_si_odoo_est_branche(self):
        self.assertFalse(self.client.get("/api/settings").json()["odoo"]["configured"])

    def test_une_panne_reseau_odoo_est_rapportee_sans_500(self):
        from app.odoo import OdooGateway, OdooUnavailable

        class Panne(OdooGateway):
            def meetings(self, **_):
                raise OdooUnavailable("Serveur Odoo injoignable.")

        app = create_app(
            self.settings,
            database=self.db,
            gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
            odoo_factory=lambda _: Panne(url="x", database="y", login="z", api_key="k"),
        )
        with TestClient(app) as client:
            vue = client.get("/api/odoo/meetings").json()
        self.assertFalse(vue["available"])
        self.assertIn("injoignable", vue["reason"])


class SondeTestCase(_Fixture):
    """La sonde propose un dossier ; elle n'écrit jamais dans Odoo."""

    def setUp(self) -> None:
        super().setUp()
        from app.sonde import Indices
        from cloud_transcription import CloudUsage
        import app.main as main_module

        self._vrai_identifier = main_module.identifier
        self.indices = Indices(
            organisations=["Acritec", "T'Knoweb"],
            personnes=["David JAUCH"],
            sujets=["facturation électronique"],
            resume="Point sur la facturation électronique chez Acritec.",
            usage=CloudUsage(model="gemini-3.1-flash-lite", input_tokens=1200,
                             output_tokens=80, cost_usd=0.0004),
        )
        self.sondes: list[str] = []

        def fausse_sonde(chemin, **_):
            self.sondes.append(chemin)
            return self.indices

        main_module.identifier = fausse_sonde

    def tearDown(self) -> None:
        import app.main as main_module

        main_module.identifier = self._vrai_identifier
        super().tearDown()

    def _app_avec_odoo(self, passerelle):
        return create_app(
            self.settings,
            database=self.db,
            gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
            odoo_factory=lambda _: passerelle,
        )

    def test_refuse_une_fenetre_vide(self):
        self.assertEqual(self.client.post("/api/probe", content=b"").status_code, 400)

    def test_refuse_une_reunion_entiere(self):
        from app.main import MAX_SONDE_BYTES

        reponse = self.client.post("/api/probe", content=b"x" * (MAX_SONDE_BYTES + 1))
        self.assertEqual(reponse.status_code, 413)

    def test_rend_les_indices_et_facture_la_sonde(self):
        vue = self.client.post("/api/probe", content=b"des octets audio").json()
        self.assertEqual(vue["clues"]["organisations"], ["Acritec", "T'Knoweb"])
        self.assertAlmostEqual(vue["cost_usd"], 0.0004)
        # Facturée sur le budget d'équipe, comme une transcription.
        self.assertAlmostEqual(self.db.month_spend_usd(), 0.0004)

    def test_la_fenetre_ne_survit_pas_a_la_sonde(self):
        self.client.post("/api/probe", content=b"des octets audio")
        self.assertEqual(self.sondes and Path(self.sondes[0]).exists(), False)

    def test_sans_cle_odoo_la_sonde_repond_quand_meme(self):
        """Odoo enrichit, il ne conditionne pas : pas de clé, pas de
        candidats, mais les indices restent."""
        vue = self.client.post("/api/probe", content=b"audio").json()
        self.assertEqual(vue["candidates"], [])
        self.assertTrue(vue["clues"]["personnes"])

    def test_propose_les_dossiers_trouves_et_dit_pourquoi(self):
        from app.odoo import OdooGateway

        class Passerelle(OdooGateway):
            def __init__(self):
                super().__init__(url="u", database="d", login="l", api_key="k")
                self.termes: list[str] = []

            def search_records(self, terme, limit=8):
                self.termes.append(terme)
                if terme == "Acritec":
                    return [{"model": "crm.lead", "id": 364, "name": "Acritec",
                             "partner": "ACRITEC, David JAUCH", "updated": "2026-09-17"}]
                return []

        passerelle = Passerelle()
        with TestClient(self._app_avec_odoo(passerelle)) as client:
            vue = client.post("/api/probe", content=b"audio").json()
        self.assertEqual(len(vue["candidates"]), 1)
        self.assertEqual(vue["candidates"][0]["id"], 364)
        self.assertEqual(vue["candidates"][0]["matched"], "Acritec")
        # Les sociétés d'abord : un dossier se retrouve par son client.
        self.assertEqual(passerelle.termes[0], "Acritec")

    def test_s_arrete_au_premier_groupe_qui_trouve(self):
        """Une fois la société reconnue, chercher aussi les personnes et
        les sujets ne fait que noyer le bon dossier."""
        from app.odoo import OdooGateway

        class Passerelle(OdooGateway):
            def __init__(self):
                super().__init__(url="u", database="d", login="l", api_key="k")
                self.termes: list[str] = []

            def search_records(self, terme, limit=8):
                self.termes.append(terme)
                return [{"model": "crm.lead", "id": 364, "name": "Acritec",
                         "partner": "", "updated": "2026-09-17"}]

        passerelle = Passerelle()
        with TestClient(self._app_avec_odoo(passerelle)) as client:
            vue = client.post("/api/probe", content=b"audio").json()
        self.assertEqual([c["id"] for c in vue["candidates"]], [364])
        self.assertNotIn("David JAUCH", passerelle.termes)
        self.assertNotIn("facturation électronique", passerelle.termes)

    def test_ignore_notre_propre_nom_et_notre_produit(self):
        """« Odoo » et « Ekonum » sont dans presque tous nos dossiers :
        les chercher ne désigne personne."""
        from app.odoo import OdooGateway
        from app.sonde import Indices

        self.indices = Indices(organisations=["Odoo", "Ekonum", "Acritec"])

        class Passerelle(OdooGateway):
            def __init__(self):
                super().__init__(url="u", database="d", login="l", api_key="k")
                self.termes: list[str] = []

            def search_records(self, terme, limit=8):
                self.termes.append(terme)
                return []

        passerelle = Passerelle()
        with TestClient(self._app_avec_odoo(passerelle)) as client:
            client.post("/api/probe", content=b"audio")
        self.assertEqual(passerelle.termes, ["Acritec"])

    def test_l_enquete_mene_la_proposition_et_les_deux_etapes_sont_facturees(self):
        """Écoute puis enquête : deux appels, deux lignes de dépense."""
        from unittest import mock

        from app import enqueteur
        from app.odoo import OdooGateway

        class Passerelle(OdooGateway):
            def __init__(self):
                super().__init__(url="u", database="d", login="l", api_key="k")

            def search_records(self, terme, limit=8, modeles=None):
                return [{"model": "crm.lead", "id": 364, "name": "Acritec",
                         "partner": "ACRITEC", "updated": "2026-09-17"}]

            def resume_dossier(self, modele, record_id):
                return {"model": modele, "id": record_id, "name": "Acritec",
                        "partner": "ACRITEC", "updated": "2026-09-17", "chatter": []}

        faux = FauxGemini([
            _appel("chercher", terme="Acritec"),
            _appel("conclure", modele="crm.lead", record_id=364,
                   confiance="probable", raison="Le chatter parle de Chorus."),
        ])
        with mock.patch.object(enqueteur, "GeminiClient", faux):
            with TestClient(self._app_avec_odoo(Passerelle())) as client:
                vue = client.post("/api/probe", content=b"audio").json()

        self.assertEqual(vue["investigation"]["confidence"], "probable")
        self.assertEqual(vue["investigation"]["record"]["id"], 364)
        self.assertIn("Chorus", vue["investigation"]["reason"])
        # La trace se montre : une proposition qu'on ne peut pas
        # contredire est une proposition qu'on ne peut pas refuser.
        self.assertTrue(vue["investigation"]["trace"])
        self.assertEqual([c["id"] for c in vue["candidates"]], [364])
        self.assertGreater(self.db.month_spend_usd(), 0.0004)

    def test_sans_cle_odoo_l_enquete_renonce_sans_bruit(self):
        vue = self.client.post("/api/probe", content=b"audio").json()
        self.assertIsNone(vue["investigation"]["record"])
        self.assertIn("clé API Odoo", vue["investigation"]["reason"])

    def test_une_panne_odoo_laisse_les_indices_intacts(self):
        from app.odoo import OdooGateway, OdooUnavailable

        class Panne(OdooGateway):
            def search_records(self, terme, limit=8):
                raise OdooUnavailable("Serveur Odoo injoignable.")

        passerelle = Panne(url="u", database="d", login="l", api_key="k")
        with TestClient(self._app_avec_odoo(passerelle)) as client:
            vue = client.post("/api/probe", content=b"audio").json()
        self.assertEqual(vue["candidates"], [])
        self.assertIn("Acritec", vue["clues"]["organisations"])


class FauxGemini:
    """Rejoue une suite de réponses Gemini, tour par tour."""

    def __init__(self, tours):
        self.tours = list(tours)
        self.recus = []

    def __call__(self, api_key, **_):
        return self

    def generate_with_tools(self, *, model_id, contents, tools, system=""):
        self.recus.append(contents)
        return self.tours.pop(0)


def _appel(nom, **args):
    """Un appel d'outil, signature de raisonnement comprise : Gemini 3
    refuse le tour suivant si elle ne lui revient pas."""
    return {
        "candidates": [{"content": {"role": "model", "parts": [{
            "functionCall": {"name": nom, "args": args},
            "thoughtSignature": f"sig-{nom}",
        }]}}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20},
    }


def _prose(texte):
    return {
        "candidates": [{"content": {"parts": [{"text": texte}]}}],
        "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 10},
    }


class EnqueteurTestCase(unittest.TestCase):
    """Chercher, lire, se raviser — puis conclure ou renoncer."""

    INDICES = {"organisations": ["Acritec"], "personnes": [], "sujets": [],
               "resume": "Facturation électronique."}

    def _mener(self, tours, *, chercher=None, lire=None, **kwargs):
        from unittest import mock

        from app import enqueteur

        faux = FauxGemini(tours)
        dossier = {"model": "crm.lead", "id": 364, "name": "Acritec",
                   "partner": "ACRITEC, David JAUCH", "updated": "2026-09-17",
                   "chatter": []}
        with mock.patch.object(enqueteur, "GeminiClient", faux):
            conclusion = enqueteur.enqueter(
                self.INDICES,
                chercher=chercher or (lambda terme, modeles: [dossier]),
                lire=lire or (lambda modele, record_id: dossier),
                api_key="k",
                **kwargs,
            )
        return conclusion, faux

    def test_l_agenda_se_consulte_en_premier_et_une_seule_fois(self):
        """Une réunion inscrite à l'heure de l'enregistrement pointe
        souvent déjà le dossier : c'est le signal le plus fiable."""
        from unittest import mock

        from app import enqueteur

        appels = {"n": 0}

        def agenda():
            appels["n"] += 1
            return [{"name": "Quentin Seyve", "start": "2026-09-21 16:00:00",
                     "attendees": ["Robin"], "resource_model": "crm.lead",
                     "resource_id": 898}]

        faux = FauxGemini([
            _appel("agenda"),
            _appel("agenda"),
            _appel("conclure", modele="crm.lead", record_id=898,
                   confiance="probable", raison="La réunion pointe ce dossier."),
        ])
        fiche = {"model": "crm.lead", "id": 898, "name": "Seyve", "partner": "",
                 "updated": "2026-09-21", "chatter": []}
        with mock.patch.object(enqueteur, "GeminiClient", faux):
            conclusion = enqueteur.enqueter(
                self.INDICES,
                chercher=lambda terme, modeles: [],
                lire=lambda modele, record_id: fiche,
                agenda=agenda,
                api_key="k",
            )
        self.assertEqual(conclusion.dossier["id"], 898)
        self.assertEqual(appels["n"], 1, "l'agenda ne se relit pas à chaque tour")
        self.assertIn("agenda consulté → 1 réunion(s)", conclusion.journal)

    def test_sans_agenda_l_enquete_continue(self):
        conclusion, _ = self._mener([
            _appel("agenda"),
            _appel("conclure", confiance="aucune", raison="Rien dans l'agenda."),
        ])
        self.assertIsNone(conclusion.dossier)
        self.assertIn("agenda indisponible", conclusion.journal)

    def test_cherche_puis_conclut(self):
        conclusion, faux = self._mener([
            _appel("chercher", terme="Acritec"),
            _appel("conclure", modele="crm.lead", record_id=364,
                   confiance="probable", raison="Le chatter parle de Chorus."),
        ])
        self.assertEqual(conclusion.dossier["id"], 364)
        self.assertEqual(conclusion.confiance, "probable")
        self.assertIn("cherché « Acritec » → 1 dossier(s)", conclusion.journal)
        # La signature du raisonnement est renvoyée telle quelle.
        self.assertIn("sig-chercher", json.dumps(faux.recus[-1]))
        # Le résultat de l'outil est bien renvoyé au modèle au tour suivant.
        self.assertIn("functionResponse", json.dumps(faux.recus[-1]))

    def test_une_panne_odoo_est_racontee_au_modele_pas_levee(self):
        """Un outil en échec doit permettre de changer de piste, pas
        faire tomber l'enquête."""
        def chercher_casse(terme, modeles):
            raise RuntimeError("Serveur Odoo injoignable.")

        conclusion, faux = self._mener(
            [
                _appel("chercher", terme="Acritec"),
                _appel("conclure", confiance="aucune", raison="Odoo muet."),
            ],
            chercher=chercher_casse,
        )
        self.assertIsNone(conclusion.dossier)
        self.assertIn("injoignable", json.dumps(faux.recus[-1]))
        self.assertIn("chercher en échec : Serveur Odoo injoignable.",
                      conclusion.journal)

    def test_ne_refait_pas_deux_fois_la_meme_recherche(self):
        """Répéter une recherche coûte un tour et n'apprend rien."""
        appels: list[str] = []

        def compter(terme, modeles):
            appels.append(terme)
            return []

        conclusion, _ = self._mener(
            [
                _appel("chercher", terme="Acritec"),
                _appel("chercher", terme="acritec"),
                _appel("conclure", confiance="aucune", raison="Rien trouvé."),
            ],
            chercher=compter,
        )
        self.assertEqual(appels, ["Acritec"])
        self.assertIn("« acritec » déjà cherché", conclusion.journal)

    def test_les_alternatives_sont_relues_pour_etre_affichables(self):
        """Se corriger doit coûter un clic, pas une nouvelle enquête."""
        fiches = {
            ("crm.lead", 364): {"model": "crm.lead", "id": 364, "name": "Acritec",
                                "partner": "ACRITEC", "updated": "2026-09-17",
                                "chatter": []},
            ("project.task", 1376): {"model": "project.task", "id": 1376,
                                     "name": "Refonte API Visiotec",
                                     "partner": "ACRITEC", "updated": "2026-09-10",
                                     "chatter": []},
        }
        conclusion, _ = self._mener(
            [_appel("conclure", modele="crm.lead", record_id=364, confiance="probable",
                    raison="L'équipe suit Acritec ici.",
                    autres=[{"modele": "project.task", "record_id": 1376,
                             "raison": "Traite du flux de vente."},
                            {"modele": "crm.lead", "record_id": 364,
                             "raison": "Doublon du retenu."}])],
            lire=lambda modele, record_id: fiches[(modele, record_id)],
        )
        self.assertEqual(conclusion.dossier["id"], 364)
        # Le doublon du dossier retenu ne se répète pas dans la liste.
        self.assertEqual([a["id"] for a in conclusion.autres], [1376])
        self.assertEqual(conclusion.autres[0]["name"], "Refonte API Visiotec")

    def test_renoncer_est_une_reponse(self):
        conclusion, _ = self._mener([
            _appel("conclure", confiance="aucune", raison="Deux clients possibles."),
        ])
        self.assertIsNone(conclusion.dossier)
        self.assertEqual(conclusion.confiance, "aucune")
        self.assertIn("Deux clients", conclusion.raison)

    def test_ne_conclut_pas_sur_un_dossier_illisible(self):
        """Conclure sur un dossier qu'on ne sait pas relire n'a pas de
        sens : on rend la main."""
        def lire_casse(modele, record_id):
            raise RuntimeError("Droits insuffisants.")

        conclusion, _ = self._mener(
            [_appel("conclure", modele="crm.lead", record_id=364,
                    confiance="certaine", raison="C'est Acritec.")],
            lire=lire_casse,
        )
        self.assertIsNone(conclusion.dossier)
        self.assertEqual(conclusion.confiance, "aucune")

    def test_le_dernier_tour_force_la_conclusion(self):
        """Un modèle qui enquête encore à la fin rendrait la main sans
        rien dire, alors qu'il a déjà tout lu."""
        conclusion, faux = self._mener(
            [
                _appel("chercher", terme="Acritec"),
                _appel("chercher", terme="Acritech"),
                _appel("conclure", modele="crm.lead", record_id=364,
                       confiance="probable", raison="Le seul dossier actif."),
            ],
            tours_max=3,
        )
        self.assertEqual(conclusion.dossier["id"], 364)
        dernier = json.dumps(faux.recus[-1])
        self.assertIn("Dernier tour", dernier)
        self.assertIn("Il te reste 1 tour(s)", dernier)

    def test_s_arrete_quand_meme_si_le_dernier_tour_n_aboutit_pas(self):
        conclusion, _ = self._mener(
            [_appel("chercher", terme="Acritec") for _ in range(3)],
            tours_max=3,
        )
        self.assertIsNone(conclusion.dossier)
        self.assertIn("Arrêt après 3 tours sans conclusion.", conclusion.journal)

    def test_une_reponse_en_prose_vaut_renoncement(self):
        conclusion, _ = self._mener([_prose("Je ne trouve rien de probant.")])
        self.assertIsNone(conclusion.dossier)
        self.assertIn("probant", conclusion.raison)

    def test_chaque_tour_est_facture(self):
        conclusion, _ = self._mener([
            _appel("chercher", terme="Acritec"),
            _appel("conclure", modele="crm.lead", record_id=364,
                   confiance="certaine", raison="Vérifié."),
        ])
        self.assertEqual(conclusion.usage.input_tokens, 200)
        self.assertGreater(conclusion.usage.cost_usd, 0)


class OdooChatterHttpTestCase(unittest.TestCase):
    """Le vrai client JSON-2, doublé au niveau HTTP.

    C'est la couche où se trouve le piège : `message_post` échappe le
    HTML, et rien au-dessus ne peut s'en apercevoir."""

    def _client(self, reponses):
        import io

        from app.chatter import OdooChatter

        appels = []

        class Fermable(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *_): return False

        def opener(requete, timeout=None):
            appels.append((requete.full_url.rsplit("/json/2/", 1)[-1],
                           json.loads(requete.data.decode())))
            return Fermable(json.dumps(reponses.pop(0)).encode())

        return OdooChatter("https://odoo.test", "cle", opener=opener), appels

    def test_le_corps_est_reecrit_apres_avoir_ete_echappe(self):
        chatter, appels = self._client([None, [{"id": 4242}], True])
        message_id = chatter.publier("crm.lead", 364, "<details>coucou</details>")
        self.assertEqual(message_id, 4242)
        chemins = [c for c, _ in appels]
        self.assertEqual(chemins, ["crm.lead/message_post",
                                   "mail.message/search_read", "mail.message/write"])
        # Le corps final est le HTML voulu, marqueur retiré.
        self.assertEqual(appels[-1][1]["vals"]["body"], "<details>coucou</details>")
        self.assertEqual(appels[0][1]["subtype_xmlid"], "mail.mt_note")

    def test_le_ping_passe_par_le_meme_chemin_et_signe_odoobot(self):
        """Le ping affichait « &lt;b&gt; » : c'est la même API, donc le
        même piège."""
        chatter, appels = self._client(
            [[{"id": 4}], None, [{"id": 77}], True]
        )
        message_id = chatter.prevenir(10, "<b>Transcription déposée</b>")
        self.assertEqual(message_id, 77)
        self.assertEqual(appels[0][0], "discuss.channel/search_read")
        self.assertEqual(appels[1][0], "discuss.channel/message_post")
        self.assertEqual(appels[1][1]["author_id"], 2)
        self.assertEqual(appels[-1][1]["vals"]["body"], "<b>Transcription déposée</b>")

    def test_sans_conversation_le_ping_ne_poste_rien(self):
        chatter, appels = self._client([[]])
        self.assertIsNone(chatter.prevenir(10, "<b>x</b>"))
        self.assertEqual(len(appels), 1)


class ConfirmationTestCase(unittest.TestCase):
    """Une certitude qui ne se répète pas n'en est pas une."""

    INDICES = {"organisations": ["Acritec"], "personnes": [], "sujets": [],
               "resume": "Facturation."}

    def _confirmer(self, tours, fiches):
        from unittest import mock

        from app import enqueteur

        faux = FauxGemini(tours)
        with mock.patch.object(enqueteur, "GeminiClient", faux):
            return enqueteur.enqueter_confirme(
                self.INDICES,
                chercher=lambda terme, modeles: [],
                lire=lambda modele, record_id: fiches[(modele, record_id)],
                api_key="k",
            )

    FICHES = {
        ("crm.lead", 364): {"model": "crm.lead", "id": 364, "name": "Acritec",
                            "partner": "ACRITEC", "updated": "2026-09-17",
                            "chatter": []},
        ("project.task", 1376): {"model": "project.task", "id": 1376,
                                 "name": "Refonte API Visiotec", "partner": "ACRITEC",
                                 "updated": "2026-09-10", "chatter": []},
    }

    def test_deux_enquetes_d_accord_gardent_la_certitude(self):
        conclusion = self._confirmer(
            [
                _appel("conclure", modele="crm.lead", record_id=364,
                       confiance="certaine", raison="L'équipe suit Acritec ici."),
                _appel("conclure", modele="crm.lead", record_id=364,
                       confiance="certaine", raison="Idem."),
            ],
            self.FICHES,
        )
        self.assertEqual(conclusion.confiance, "certaine")
        self.assertEqual(conclusion.dossier["id"], 364)
        self.assertIn("seconde enquête : même dossier, certitude confirmée",
                      conclusion.journal)

    def test_un_desaccord_ramene_la_certitude_a_une_question(self):
        conclusion = self._confirmer(
            [
                _appel("conclure", modele="project.task", record_id=1376,
                       confiance="certaine", raison="La tâche traite du flux."),
                _appel("conclure", modele="crm.lead", record_id=364,
                       confiance="certaine", raison="L'opportunité suit le client."),
            ],
            self.FICHES,
        )
        self.assertEqual(conclusion.confiance, "probable")
        self.assertEqual(conclusion.dossier["id"], 1376)
        # Le dossier de la seconde enquête se propose juste en dessous.
        self.assertEqual(conclusion.autres[0]["id"], 364)
        self.assertIn("certitude ramenée", " ".join(conclusion.journal))

    def test_une_conclusion_moins_que_certaine_ne_coute_pas_un_second_tour(self):
        conclusion = self._confirmer(
            [_appel("conclure", modele="crm.lead", record_id=364,
                    confiance="probable", raison="Probablement.")],
            self.FICHES,
        )
        self.assertEqual(conclusion.confiance, "probable")
        self.assertEqual(conclusion.usage.input_tokens, 100)


class LiaisonAutomatiqueTestCase(_Fixture):
    """Lier seul quand c'est sûr, demander sinon, ne jamais casser."""

    class Chatter:
        def __init__(self, *, casse=False, canal=True):
            self.casse = casse
            self.canal = canal
            self.publies: list[tuple] = []
            self.pings: list[str] = []
            self.activites: list[tuple] = []

        def publier(self, modele, record_id, corps):
            from app.chatter import ChatterError

            if self.casse:
                raise ChatterError("Odoo a refusé la note (HTTP 500).")
            self.publies.append((modele, record_id, corps))
            return 4242

        def prevenir(self, partner_id, texte):
            if not self.canal:
                return None
            self.pings.append(texte)
            return 77

        def activite(self, modele, record_id, user_id, resume, note=""):
            self.activites.append((modele, record_id, user_id, resume))
            return 88

    def _passerelle(self, chatter):
        from app.odoo import OdooGateway

        class Passerelle(OdooGateway):
            def __init__(self):
                super().__init__(url="https://www.ekonum.fr", database="d",
                                 login="robin@ekonum.fr", api_key="k")

            def chatter(self_inner):
                return chatter

            def identite(self_inner):
                return {"user_id": 6, "partner_id": 10}

        return Passerelle()

    def _transcrire(self, chatter, **contexte):
        app = create_app(
            self.settings,
            database=self.db,
            gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
            odoo_factory=lambda _: self._passerelle(chatter),
        )
        with TestClient(app) as client:
            job = client.post("/api/jobs", json={
                "filename": "reunion.mov", "duration_seconds": 600.0,
                "model": "gemini-3.8-flash", "language": "fr",
                "context": {"client_company": "Acritec", **contexte},
            }).json()
            for fenetre in job["chunks"]:
                client.put(f"/api/jobs/{job['job_id']}/chunks/{fenetre['index']}",
                           content=b"audio")
            return client.post(f"/api/jobs/{job['job_id']}/finalize").json(), job

    def test_depose_et_previent_sans_rien_demander(self):
        chatter = self.Chatter()
        vue, job = self._transcrire(
            chatter,
            odoo_record={"model": "crm.lead", "record_id": 364},
            odoo_auto=True,
        )
        self.assertTrue(vue["odoo"]["published"])
        self.assertEqual(vue["odoo"]["message_id"], 4242)
        self.assertEqual(vue["odoo"]["notified"], "odoobot")
        self.assertEqual(chatter.publies[0][:2], ("crm.lead", 364))
        # Le lien est enregistré : reposter empilerait deux copies.
        self.assertEqual(self.db.get_job(job["job_id"])["odoo_message_id"], 4242)

    def test_sans_certitude_le_dossier_attend_un_clic(self):
        chatter = self.Chatter()
        vue, _ = self._transcrire(
            chatter, odoo_record={"model": "crm.lead", "record_id": 364}
        )
        self.assertTrue(vue["odoo"]["pending"])
        self.assertEqual(chatter.publies, [])

    def test_un_depot_rate_ne_perd_pas_la_transcription(self):
        chatter = self.Chatter(casse=True)
        vue, job = self._transcrire(
            chatter,
            odoo_record={"model": "crm.lead", "record_id": 364},
            odoo_auto=True,
        )
        self.assertFalse(vue["odoo"]["published"])
        self.assertIn("refusé", vue["odoo"]["error"])
        self.assertTrue(vue["transcript"])
        # Rien n'est marqué comme publié : le bouton reste disponible.
        self.assertIsNone(self.db.get_job(job["job_id"])["odoo_message_id"])

    def test_sans_conversation_odoobot_on_pose_une_activite(self):
        chatter = self.Chatter(canal=False)
        vue, _ = self._transcrire(
            chatter,
            odoo_record={"model": "crm.lead", "record_id": 364},
            odoo_auto=True,
        )
        self.assertEqual(vue["odoo"]["notified"], "activite")
        self.assertEqual(chatter.activites[0][:3], ("crm.lead", 364, 6))

    def test_sans_dossier_choisi_rien_ne_se_passe(self):
        chatter = self.Chatter()
        vue, _ = self._transcrire(chatter)
        self.assertEqual(vue["odoo"], {})


class AgendaTestCase(unittest.TestCase):
    """Le filtre d'agenda ne doit pas écarter la réunion qu'on cherche."""

    def test_une_reunion_a_un_seul_participant_odoo_compte(self):
        """La réunion « Quentin Seyve » n'avait que Robin en
        participant : l'invité n'était pas dans la base."""
        from unittest import mock

        from app import odoo as module

        passerelle = module.OdooGateway(url="u", database="d", login="l", api_key="k")
        with mock.patch.object(module, "search_meeting_events",
                               return_value=[]) as cherche:
            passerelle.meetings()
        self.assertEqual(cherche.call_args.kwargs["min_attendees"], 1)


class InstantTestCase(unittest.TestCase):
    """L'heure de l'enregistrement, telle que le navigateur l'envoie."""

    def test_lit_un_horodatage_du_navigateur(self):
        from app.main import _instant

        lu = _instant("2026-09-21T16:34:00.000Z")
        self.assertEqual(lu.hour, 16)
        self.assertIsNotNone(lu.tzinfo)

    def test_un_horodatage_illisible_vaut_maintenant(self):
        from app.main import _instant

        self.assertIsNone(_instant("hier soir"))
        self.assertIsNone(_instant(""))


class SeuilDeLiaisonTestCase(unittest.TestCase):
    """Le seuil décide seul de ce qui se lie sans demander."""

    def test_l_echelle_est_respectee(self):
        from app.main import liaison_sans_demander

        self.assertTrue(liaison_sans_demander("certaine", "certaine"))
        self.assertFalse(liaison_sans_demander("probable", "certaine"))
        self.assertTrue(liaison_sans_demander("probable", "probable"))
        self.assertTrue(liaison_sans_demander("certaine", "probable"))
        self.assertFalse(liaison_sans_demander("incertaine", "probable"))

    def test_jamais_et_valeurs_inconnues_ne_lient_rien(self):
        from app.main import liaison_sans_demander

        self.assertFalse(liaison_sans_demander("certaine", "jamais"))
        self.assertFalse(liaison_sans_demander("certaine", ""))
        self.assertFalse(liaison_sans_demander("aucune", "certaine"))


class ApiTokenTestCase(_Fixture):
    """Jetons d'API : ce qui ouvre la porte aux appels machine."""

    def _mint(self, name="script de test") -> str:
        response = self.client.post("/api/tokens", json={"name": name})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["token"]

    def test_un_jeton_ouvre_l_api(self):
        jeton = self._mint()
        client = TestClient(self.app, headers={"Authorization": f"Bearer {jeton}"})
        response = client.post(
            "/api/jobs",
            json={
                "filename": "machine.mov",
                "duration_seconds": 600,
                "model": "gemini-3.8-flash",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

    def test_le_jeton_en_clair_n_est_pas_en_base(self):
        """Un vol de base ne doit pas rendre les jetons utilisables."""
        jeton = self._mint()
        with self.db.connect() as conn:
            lignes = conn.execute("SELECT * FROM api_tokens").fetchall()
        self.assertEqual(len(lignes), 1)
        self.assertNotIn(jeton, json.dumps([dict(r) for r in lignes]))

    def test_un_jeton_inconnu_est_refuse(self):
        client = TestClient(self.app, headers={"Authorization": "Bearer ekt_inconnu"})
        self.assertEqual(client.get("/api/jobs").status_code, 401)

    def test_un_jeton_revoque_ne_sert_plus(self):
        jeton = self._mint()
        identifiant = self.client.get("/api/tokens").json()[0]["id"]
        self.assertEqual(self.client.delete(f"/api/tokens/{identifiant}").status_code, 204)

        client = TestClient(self.app, headers={"Authorization": f"Bearer {jeton}"})
        self.assertEqual(client.get("/api/jobs").status_code, 401)

    def test_un_jeton_ne_peut_pas_en_fabriquer_un_autre(self):
        """Un jeton volé ne doit pas pouvoir se reproduire ni révoquer
        ceux des collègues."""
        jeton = self._mint()
        client = TestClient(self.app, headers={"Authorization": f"Bearer {jeton}"})
        self.assertEqual(client.post("/api/tokens", json={"name": "x"}).status_code, 403)
        self.assertEqual(client.get("/api/tokens").status_code, 403)
        self.assertEqual(client.delete("/api/tokens/1").status_code, 403)

    def test_le_jeton_porte_l_identite_de_son_proprietaire(self):
        """Les traitements créés par API appartiennent à la personne, pas
        à une identité machine anonyme : le cloisonnement et l'attribution
        des coûts valent donc comme pour une session humaine."""
        jeton = self._mint()
        client = TestClient(self.app, headers={"Authorization": f"Bearer {jeton}"})
        cree = client.post(
            "/api/jobs",
            json={"filename": "machine.mov", "duration_seconds": 600,
                  "model": "gemini-3.8-flash"},
        ).json()
        # Visible depuis la session humaine du même compte.
        self.assertIn(cree["job_id"], [j["job_id"] for j in self.client.get("/api/jobs").json()])

    def test_le_dernier_usage_est_trace(self):
        jeton = self._mint()
        self.assertIsNone(self.client.get("/api/tokens").json()[0]["last_used_at"])
        TestClient(self.app, headers={"Authorization": f"Bearer {jeton}"}).get("/api/jobs")
        self.assertIsNotNone(self.client.get("/api/tokens").json()[0]["last_used_at"])

    def test_un_jeton_ne_voit_pas_les_traitements_d_un_autre_compte(self):
        jeton = self._mint()
        autre = self.db.user_id_for_email("luka@ekonum.fr")
        prive = self.db.create_job(
            owner_id=autre, filename="prive.mov", duration_seconds=60,
            model="gemini-3.8-flash", language="fr", context={}, chunks=[(0.0, 60.0)],
        )
        client = TestClient(self.app, headers={"Authorization": f"Bearer {jeton}"})
        self.assertEqual(client.get(f"/api/jobs/{prive}").status_code, 404)


class IdentityTestCase(_Fixture):
    def test_l_interface_sait_qui_est_connecte(self):
        vue = self.client.get("/api/me").json()
        self.assertEqual(vue["email"], "robin@ekonum.fr")
        self.assertEqual(vue["via"], "Cloudflare Access")

    def test_un_appel_machine_se_signale_comme_tel(self):
        jeton = self.client.post("/api/tokens", json={"name": "script"}).json()["token"]
        client = TestClient(self.app, headers={"Authorization": f"Bearer {jeton}"})
        vue = client.get("/api/me").json()
        self.assertEqual(vue["email"], "robin@ekonum.fr")
        self.assertEqual(vue["via"], "jeton d'API")


class ImportTestCase(_Fixture):
    """Reprise de la bibliothèque macOS, poussée depuis le poste."""

    REUNION = {
        "filename": "Enregistrement de l'écran 2026-07-03.mov",
        "created_at": "2026-07-06 18:01:04",
        "title": "Acritec - Revue mensuelle",
        "duration_seconds": 5400,
        "model": "gemini-2.5-flash",
        "transcript": "Robin : on migre vers Odoo 19.",
        "speakers": {"Intervenant 1": "Robin"},
        "technical_terms": ["Odoo", "Acritec"],
        "cost_usd": 0.42,
        "segments": [
            {"start": 0, "end": 5, "speaker": "Robin", "text": "on migre vers Odoo 19"},
        ],
    }

    def test_une_reunion_reprise_arrive_complete(self):
        vue = self.client.post("/api/jobs/import", json=self.REUNION).json()
        self.assertTrue(vue["imported"])

        detail = self.client.get(f"/api/jobs/{vue['job_id']}/detail").json()
        self.assertEqual(detail["title"], "Acritec - Revue mensuelle")
        self.assertEqual(detail["status"], "termine")
        self.assertEqual(detail["speakers"], {"Intervenant 1": "Robin"})
        self.assertEqual(len(detail["segments"]), 1)
        self.assertIn("Odoo 19", detail["transcript"])

    def test_la_reprise_est_rejouable_sans_doublon(self):
        """Une reprise de plusieurs années ne réussit jamais du premier
        coup : il faut pouvoir relancer."""
        premier = self.client.post("/api/jobs/import", json=self.REUNION).json()
        second = self.client.post("/api/jobs/import", json=self.REUNION).json()
        self.assertTrue(premier["imported"])
        self.assertFalse(second["imported"])
        self.assertEqual(premier["job_id"], second["job_id"])
        self.assertEqual(len(self.client.get("/api/jobs").json()), 1)

    def test_le_vocabulaire_d_equipe_herite_de_l_historique(self):
        self.client.post("/api/jobs/import", json=self.REUNION)
        termes = [t["term"] for t in self.client.get("/api/vocabulary").json()]
        self.assertIn("Acritec", termes)
        self.assertIn("Odoo", termes)

    def test_une_reunion_reprise_est_cherchable(self):
        self.client.post("/api/jobs/import", json=self.REUNION)
        hits = self.client.get("/api/search", params={"q": "migre"}).json()
        self.assertEqual(len(hits), 1)

    def test_la_reprise_passe_par_un_jeton_d_api(self):
        """C'est le chemin réel : un script sur le poste, pas un humain."""
        jeton = self.client.post("/api/tokens", json={"name": "reprise"}).json()["token"]
        client = TestClient(self.app, headers={"Authorization": f"Bearer {jeton}"})
        self.assertTrue(client.post("/api/jobs/import", json=self.REUNION).json()["imported"])


class ChatterTestCase(_Fixture):
    """Dépôt dans le chatter Odoo — le geste qui remplace la recopie."""

    def _job_termine(self) -> int:
        vue = self.client.post("/api/jobs/import", json={
            "filename": "reunion.mov", "created_at": "2026-07-06 18:01:04",
            "title": "Acritec - Revue mensuelle",
            "transcript": "Robin : on migre vers Odoo 19.",
            "segments": [{"start": 0, "end": 5, "speaker": "Robin", "text": "on migre"}],
        }).json()
        return vue["job_id"]

    def _avec_odoo(self, publier):
        """Monte l'app avec une passerelle Odoo dont l'écriture est doublée."""
        from app.odoo import OdooGateway

        class Passerelle(OdooGateway):
            @property
            def configured(self):
                return True

            def chatter(self):
                return publier

        # Le dépôt exige une clé personnelle : sans elle, la note serait
        # signée d'un compte partagé.
        self.client.put("/api/me/odoo",
                        json={"login": "robin@ekonum.fr", "api_key": "cle-odoo"})
        return create_app(
            self.settings, database=self.db,
            gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
            odoo_factory=lambda _: Passerelle(
                url="https://odoo.test", database="d", login="l", api_key="k"),
        )

    def test_la_note_est_un_accordeon_et_une_note_interne(self):
        """Une transcription de réunion ne doit pas partir en e-mail aux
        abonnés du dossier, et ne doit pas noyer le chatter."""
        vus = {}

        class Faux:
            def publier(self, modele, record_id, corps):
                vus.update(modele=modele, record_id=record_id, corps=corps)
                return 119205

        job_id = self._job_termine()
        app = self._avec_odoo(Faux())
        with TestClient(app) as client:
            vue = client.post(
                f"/api/jobs/{job_id}/odoo/publish",
                json={"model": "crm.lead", "record_id": 364},
            )
        self.assertEqual(vue.status_code, 200, vue.text)
        self.assertEqual(vue.json()["message_id"], 119205)
        self.assertEqual(vus["modele"], "crm.lead")
        self.assertIn("<details", vus["corps"])
        self.assertIn("Odoo 19", vus["corps"])

    def test_le_lien_est_conserve_et_visible(self):
        class Faux:
            def publier(self, *_a):
                return 119205

        job_id = self._job_termine()
        app = self._avec_odoo(Faux())
        with TestClient(app) as client:
            client.post(f"/api/jobs/{job_id}/odoo/publish",
                        json={"model": "crm.lead", "record_id": 364})
            detail = client.get(f"/api/jobs/{job_id}/detail").json()
        self.assertEqual(detail["odoo"]["record_id"], 364)
        self.assertEqual(detail["odoo"]["message_id"], 119205)
        self.assertIsNotNone(detail["odoo"]["published_at"])

    def test_on_ne_depose_pas_deux_fois(self):
        """Reposter empilerait deux copies du même texte dans le dossier."""
        class Faux:
            def publier(self, *_a):
                return 119205

        job_id = self._job_termine()
        app = self._avec_odoo(Faux())
        with TestClient(app) as client:
            self.assertEqual(client.post(
                f"/api/jobs/{job_id}/odoo/publish",
                json={"model": "crm.lead", "record_id": 364}).status_code, 200)
            second = client.post(
                f"/api/jobs/{job_id}/odoo/publish",
                json={"model": "crm.lead", "record_id": 364})
        self.assertEqual(second.status_code, 409)

    def test_une_panne_odoo_ne_perd_pas_la_transcription(self):
        from app.chatter import ChatterError

        class EnPanne:
            def publier(self, *_a):
                raise ChatterError("Odoo injoignable.")

        job_id = self._job_termine()
        app = self._avec_odoo(EnPanne())
        with TestClient(app) as client:
            vue = client.post(f"/api/jobs/{job_id}/odoo/publish",
                              json={"model": "crm.lead", "record_id": 364})
            detail = client.get(f"/api/jobs/{job_id}/detail").json()
        self.assertEqual(vue.status_code, 502)
        # Rien n'est enregistré : un nouvel essai reste possible.
        self.assertIsNone(detail["odoo"]["message_id"])
        self.assertIn("Odoo 19", detail["transcript"])

    def test_une_reunion_sans_transcription_est_refusee(self):
        body = self._create(duration=600.0)
        app = self._avec_odoo(object())
        with TestClient(app) as client:
            vue = client.post(f"/api/jobs/{body['job_id']}/odoo/publish",
                              json={"model": "crm.lead", "record_id": 364})
        self.assertEqual(vue.status_code, 409)


class OdooPersonnelTestCase(_Fixture):
    """Chacun sa clé : la note doit porter l'identité de son auteur."""

    def test_sans_cle_personnelle_le_depot_est_refuse(self):
        """Avec une clé partagée, toutes les notes seraient signées du même
        compte et l'attribution — la raison d'être du chatter — sauterait."""
        app = create_app(
            _settings(self.root, odoo_url="https://www.ekonum.fr",
                      odoo_database="ekonum"),
            database=self.db,
            gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
        )
        with TestClient(app) as client:
            job = client.post("/api/jobs/import", json={
                "filename": "r.mov", "created_at": "2026-07-06 18:01:04",
                "title": "T", "transcript": "texte",
            }).json()["job_id"]
            vue = client.post(f"/api/jobs/{job}/odoo/publish",
                              json={"model": "crm.lead", "record_id": 364})
        self.assertEqual(vue.status_code, 409)
        self.assertIn("ta clé", vue.json()["detail"])

    def test_la_cle_est_chiffree_et_jamais_rendue(self):
        pose = self.client.put("/api/me/odoo",
                               json={"login": "robin@ekonum.fr", "api_key": "cle-odoo-secrete"})
        self.assertEqual(pose.status_code, 200)

        vue = self.client.get("/api/me/odoo").json()
        self.assertTrue(vue["configured"])
        self.assertEqual(vue["login"], "robin@ekonum.fr")
        self.assertNotIn("cle-odoo-secrete", json.dumps(vue))

        with self.db.connect() as conn:
            lignes = json.dumps([dict(r) for r in conn.execute("SELECT * FROM users")])
        self.assertNotIn("cle-odoo-secrete", lignes)

    def test_un_jeton_d_api_ne_pose_pas_d_identite_odoo(self):
        """Un jeton volé ne doit pas pouvoir déposer une identité Odoo à la
        place de quelqu'un."""
        jeton = self.client.post("/api/tokens", json={"name": "s"}).json()["token"]
        client = TestClient(self.app, headers={"Authorization": f"Bearer {jeton}"})
        vue = client.put("/api/me/odoo",
                         json={"login": "x@ekonum.fr", "api_key": "12345678"})
        self.assertEqual(vue.status_code, 403)

    def test_sans_chiffrement_le_serveur_refuse_le_secret(self):
        """Stocker en clair « en attendant » est le genre de provisoire qui
        reste : on refuse plutôt que de dégrader."""
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            app = create_app(
                _settings(racine, secret_key=""), database=Database(racine / "d.db"),
                gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
            )
            with TestClient(app) as client:
                vue = client.put("/api/me/odoo",
                                 json={"login": "a@b.fr", "api_key": "12345678"})
        self.assertEqual(vue.status_code, 503)

    def test_la_cle_peut_etre_retiree(self):
        self.client.put("/api/me/odoo",
                        json={"login": "robin@ekonum.fr", "api_key": "cle-odoo"})
        self.assertEqual(self.client.delete("/api/me/odoo").status_code, 204)
        self.assertFalse(self.client.get("/api/me/odoo").json()["configured"])


class OdooSansClePersonnelleTestCase(_Fixture):
    """Sans clé personnelle, Odoo se tait — mais le dit."""

    def test_la_recherche_invite_a_poser_sa_cle(self):
        vue = self.client.get("/api/odoo/records", params={"q": "Acritec"}).json()
        self.assertFalse(vue["available"])
        self.assertIn("ton compte", vue["reason"])
        self.assertEqual(vue["records"], [])

    def test_les_suggestions_de_reunion_aussi(self):
        vue = self.client.get("/api/odoo/meetings").json()
        self.assertFalse(vue["available"])
        self.assertEqual(vue["meetings"], [])

    def test_une_cle_posee_rend_odoo_disponible(self):
        app = create_app(
            _settings(self.root, odoo_url="https://www.ekonum.fr",
                      odoo_database="ekonum"),
            database=self.db,
            gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
        )
        with TestClient(app) as client:
            self.assertFalse(client.get("/api/settings").json()["odoo"]["configured"])
            client.put("/api/me/odoo",
                       json={"login": "robin@ekonum.fr", "api_key": "cle-odoo"})
            self.assertTrue(client.get("/api/settings").json()["odoo"]["configured"])


if __name__ == "__main__":
    unittest.main()
