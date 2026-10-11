"""Récupérer l'historique depuis le Mac : le navigateur parcourt un
dossier, transcript dit ce qui est déjà là, puis le navigateur envoie."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import app as _app_package  # noqa: F401  (installe la racine du dépôt dans sys.path)

from app.db import Database
from app.main import create_app
from app.secrets import GeminiKey
from tests.test_api import FauxStockage, _Client, _settings

# Le 4 mars 2025 à 10 h 15, heure de Paris.
MARS = int(datetime(2025, 3, 4, 9, 15, tzinfo=timezone.utc).timestamp() * 1000)


def fichier(chemin, taille=40, empreinte="a", **champs):
    return {
        "id": chemin, "checksum": empreinte * 64, "name": chemin.rsplit("/", 1)[-1], "size": taille,
        "modified": MARS, "mime_type": "audio/mp4", **champs,
    }


class MacRecoveryTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings = _settings(Path(self._tmp.name), recovery_users=frozenset({"robin@ekonum.fr"}))
        self.db = Database(self.settings.db_path)
        self.stockage = FauxStockage()
        self.app = create_app(
            self.settings, database=self.db,
            gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
            stockage_factory=lambda: self.stockage,
        )
        self.client = _Client(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.moi = self.db.user_id_for_email("robin@ekonum.fr")

    def _items(self, *fichiers):
        reponse = self.client.post("/api/recovery/mac", json={"files": list(fichiers)})
        self.assertEqual(reponse.status_code, 200, reponse.text)
        return {i["id"]: i for i in reponse.json()["items"]}

    def _envoyer(self, job_id, taille, morceau=16):
        for debut in range(0, taille, morceau):
            reponse = self.client.put(f"/api/jobs/{job_id}/video?debut={debut}",
                                      content=b"m" * min(morceau, taille - debut))
            self.assertEqual(reponse.status_code, 200, reponse.text)

    def test_l_inventaire_date_et_range_comme_le_drive(self):
        items = self._items(
            fichier("Réunions/Nouvel enregistrement.m4a"),
            fichier("Copies/Nouvel enregistrement.m4a"),
            fichier("Bureau/tuto montage.mov", empreinte="b", mime_type="video/quicktime"),
        )
        reunion = items["Réunions/Nouvel enregistrement.m4a"]
        self.assertEqual(reunion["recorded_at"], "2025-03-04T10:15", "heure de Paris")
        self.assertFalse(reunion["recorded_at_from_name"])
        self.assertEqual(reunion["location"], {"kind": "mac", "name": "Réunions"})
        self.assertEqual(reunion["kind"], "meeting")
        self.assertEqual(items["Copies/Nouvel enregistrement.m4a"]["status"], "duplicate")
        self.assertEqual(items["Bureau/tuto montage.mov"]["kind"], "other")

    def test_recuperer_puis_jamais_deux_fois(self):
        f = fichier("Réunions/Point Cambon.m4a")
        vue = self.client.post("/api/recovery/mac/import", json={"file": f}).json()
        self.assertTrue(vue["upload"])
        job_id = vue["job_id"]
        self.assertEqual(self.client.post("/api/recovery/mac/done", json={"file": f, "job_id": job_id}).status_code,
                         409, "pas récupéré tant que l'envoi n'est pas fini")
        self._envoyer(job_id, 40)
        fin = self.client.post("/api/recovery/mac/done", json={"file": f, "job_id": job_id}).json()
        self.assertEqual((fin["video"], fin["original"]), (None, "left_on_mac"))
        fiche = self.client.get(f"/api/jobs/{job_id}/detail").json()
        self.assertEqual(fiche["status"], "recovered")
        self.assertTrue(fiche["video"]["presente"])
        self.assertEqual(list(self.stockage.fichiers.values()), [b"m" * 40])

        # Le même fichier, d'un autre dossier ou d'un autre poste : déjà là.
        ailleurs = fichier("Archives/Point Cambon.m4a")
        self.assertEqual((self._items(ailleurs)[ailleurs["id"]]["status"],
                          self._items(ailleurs)[ailleurs["id"]]["job_id"]), ("recovered", job_id))
        self.assertEqual(self.client.post("/api/recovery/mac/import", json={"file": ailleurs}).status_code, 409)

    def test_deja_recupere_depuis_le_drive(self):
        self.db.record_recovered(source="drive", external_id="f1", checksum="md5", size_bytes=40,
                                 name="Point Cambon.m4a", job_id=None, user_id=self.moi)
        f = fichier("Point Cambon.m4a")
        self.assertEqual(self._items(f)[f["id"]]["status"], "recovered")
        self.assertEqual(self.client.post("/api/recovery/mac/import", json={"file": f}).status_code, 409)

    def test_un_envoi_interrompu_se_reprend_ou_s_abandonne(self):
        f = fichier("Point Cambon.m4a")
        premier = self.client.post("/api/recovery/mac/import", json={"file": f}).json()["job_id"]
        second = self.client.post("/api/recovery/mac/import", json={"file": f}).json()["job_id"]
        self.assertEqual(premier, second, "pas de seconde réunion pour le même fichier")
        self.assertEqual(self.client.post("/api/recovery/mac/abandon",
                                          json={"file": f, "job_id": premier}).status_code, 204)
        self.assertIsNone(self.db.get_job(premier))

    def test_abandonner_ne_retire_jamais_une_reunion_terminee(self):
        f = fichier("Point Cambon.m4a")
        job_id = self.client.post("/api/recovery/mac/import", json={"file": f}).json()["job_id"]
        self._envoyer(job_id, 40)
        self.client.post("/api/recovery/mac/abandon", json={"file": f, "job_id": job_id})
        self.assertIsNotNone(self.db.get_job(job_id))

    def _reunion_deja_transcrite(self, owner_id=None):
        job_id = self.db.create_job(owner_id=owner_id or self.moi, filename="Point Cambon.mov", duration_seconds=600,
                                    model="", language="fr", context={}, chunks=[])
        self.db.set_meeting_date(job_id, "2025-03-04T09:30")
        return job_id

    def test_ranger_avec_la_reunion_existante(self):
        job_id = self._reunion_deja_transcrite()
        f = fichier("Point Cambon.m4a")
        self.assertEqual((self._items(f)[f["id"]]["status"], self._items(f)[f["id"]]["job_id"]),
                         ("in_library", job_id))
        vue = self.client.post("/api/recovery/mac/attach", json={"file": f, "job_id": job_id}).json()
        self.assertEqual((vue["job_id"], vue["upload"]), (job_id, True))
        self._envoyer(job_id, 40)
        fin = self.client.post("/api/recovery/mac/done", json={"file": f, "job_id": job_id}).json()
        self.assertEqual(fin["video"], "attached")
        self.assertEqual(self.client.get("/api/jobs").headers["x-total-count"], "1", "pas de seconde réunion")

    def test_une_reunion_qui_a_sa_video_la_garde(self):
        job_id = self._reunion_deja_transcrite()
        self.db.ouvrir_envoi_video(job_id, "", 99)
        self.db.terminer_envoi_video(job_id, "video-mac")
        f = fichier("Point Cambon.m4a")
        vue = self.client.post("/api/recovery/mac/attach", json={"file": f, "job_id": job_id}).json()
        self.assertEqual((vue["upload"], vue["video"]), (False, "kept"))
        self.assertEqual(self.db.get_job(job_id)["video_file_id"], "video-mac")
        self.assertEqual(self._items(f)[f["id"]]["status"], "recovered")

    def test_on_ne_range_pas_avec_la_reunion_d_un_autre(self):
        autre = self._reunion_deja_transcrite(owner_id=self.db.user_id_for_email("luka@ekonum.fr"))
        reponse = self.client.post("/api/recovery/mac/attach", json={"file": fichier("Point Cambon.m4a"), "job_id": autre})
        self.assertEqual(reponse.status_code, 404)

    def test_une_empreinte_mal_formee_est_refusee(self):
        reponse = self.client.post("/api/recovery/mac", json={"files": [fichier("x.m4a", empreinte="z")]})
        self.assertEqual(reponse.status_code, 422)


if __name__ == "__main__":
    unittest.main()
