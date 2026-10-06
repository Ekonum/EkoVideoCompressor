"""Récupérer l'historique : inventaire du Drive, puis rangement dans transcript."""

from __future__ import annotations

import base64
import io
import json
import tempfile
import unicodedata
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

import app as _app_package  # noqa: F401  (installe la racine du dépôt dans sys.path)

from app.db import Database
from app.main import create_app
from app.recovery import build_inventory, classify, library_match, recording_date, stem
from app.secrets import GeminiKey
from tests.test_api import FauxStockage, _Client, _settings


def _id_token(email: str) -> str:
    charge = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).rstrip(b"=").decode()
    return f"entete.{charge}.signature"


class RulesTestCase(unittest.TestCase):
    """Les règles de l'inventaire, sans réseau."""

    def test_le_nom_d_une_copie_redevient_celui_de_l_original(self):
        self.assertEqual(stem("Nouvel enregistrement 9_compressed.m4a"), "nouvel enregistrement 9")
        self.assertEqual(stem("Réunion Acritec (1).mp4"), "reunion acritec")

    def test_la_date_vient_du_nom_quand_il_en_porte_une(self):
        memo = {"name": "21 sept. à 18-34.m4a", "createdTime": "2026-09-24T08:00:00Z"}
        self.assertEqual(recording_date(memo), ("2026-09-21T18:34", True))
        # Un mémo de décembre déposé en janvier est de l'année d'avant.
        hiver = {"name": "30 déc. à 09-15.m4a", "createdTime": "2027-01-04T08:00:00Z"}
        self.assertEqual(recording_date(hiver)[0], "2026-12-30T09:15")
        meet = {"name": "Point Acritec - 2026/03/12 10:00 CET - Recording", "createdTime": "2026-03-12T11:00:00Z"}
        self.assertEqual(recording_date(meet), ("2026-03-12T10:00", True))

    def test_l_heure_aussi_quel_que_soit_l_enregistreur(self):
        cas = {
            "Enregistrement de l’écran 2025-03-04 à 10.15.32.mov": "2025-03-04T10:15",
            "Screen Recording 2025-03-04 at 9.15.32 PM.mov": "2025-03-04T21:15",
            # Les mémos récents : une virgule, et un espace invisible.
            "19 févr., 14.03\u200b.m4a": "2026-02-19T14:03",
            # L'enregistreur d'appels : mois d'abord, heure sur 12 h.
            "benjamin dotte_10-28-25_0514PM.amr": "2025-10-28T17:14",
            "\u202a03 27 51 11 33\u202c_10-13-25_0344PM.amr": "2025-10-13T15:44",
            "appel_01-05-26_1210AM.amr": "2026-01-05T00:10",
            # Le Mac écrit « à » en deux caractères : « a » et l'accent.
            unicodedata.normalize("NFD", "Enregistrement de l’écran 2026-06-25 à 13.59.49.mov"): "2026-06-25T13:59",
        }
        for nom, attendu in cas.items():
            with self.subTest(nom=nom):
                self.assertEqual(recording_date({"name": nom, "createdTime": "2026-03-01T08:00:00Z"}),
                                 (attendu, True))

    def test_sans_date_dans_le_nom_on_prend_la_plus_ancienne_de_drive(self):
        fichier = {"name": "Rue des Hauts Vents 4.m4a", "createdTime": "2026-04-10T09:00:00Z",
                   "modifiedTime": "2026-04-02T14:30:00Z"}
        date, sure = recording_date(fichier)
        self.assertFalse(sure)
        self.assertTrue(date.startswith("2026-04-02"))

    def test_tutoriels_et_voix_off_ne_sont_pas_des_reunions(self):
        self.assertEqual(classify({"name": "Tutoriel-plannings.mp4", "mimeType": "video/mp4"}), "other")
        self.assertEqual(classify({"name": "narration.wav", "mimeType": "audio/wav"}), "other")
        self.assertEqual(classify({"name": "Rue Fonvieille 3.m4a", "mimeType": "audio/x-m4a"}), "meeting")
        self.assertEqual(classify({"name": "planning-final.mp4", "mimeType": "video/mp4"}), "unsure")
        court = {"name": "Point rapide.mp4", "mimeType": "video/mp4",
                 "videoMediaMetadata": {"durationMillis": "40000"}}
        self.assertEqual(classify(court), "other")

    def test_les_restes_de_l_ancienne_app_ne_sont_pas_des_reunions(self):
        for nom in ("audio.wav", "audio.vad.wav", "audio_partie_03.wav"):
            with self.subTest(nom=nom):
                self.assertEqual(classify({"name": nom, "mimeType": "audio/wav"}), "other")
        self.assertEqual(classify({"name": "audio Seyve.wav", "mimeType": "audio/wav"}), "meeting")

    def test_le_nom_seul_ne_suffit_pas_a_reconnaitre_une_reunion(self):
        """« Nouvel enregistrement 9 » revient d'une année sur l'autre."""
        bibliotheque = [{"id": 7, "owner_id": 1, "filename": "Nouvel enregistrement 9.m4a",
                         "duration_seconds": 1800, "video_bytes": None, "quand": "2025-03-01T10:00:00"}]
        fichier = {"name": "Nouvel enregistrement 9_compressed.m4a"}
        self.assertIsNone(library_match(fichier, "2026-03-01T10:00", bibliotheque))
        self.assertEqual(library_match(fichier, "2025-03-02T09:00", bibliotheque)["id"], 7)

    def test_l_inventaire_ne_montre_jamais_deux_fois_le_meme_contenu(self):
        fichiers = [
            {"id": "a", "name": "21 sept. à 18-34.m4a", "mimeType": "audio/x-m4a", "size": "10",
             "md5Checksum": "m1", "createdTime": "2026-09-21T17:00:00Z"},
            {"id": "b", "name": "21 sept. à 18-34.m4a", "mimeType": "audio/x-m4a", "size": "10",
             "md5Checksum": "m1", "createdTime": "2026-09-22T08:00:00Z"},
            {"id": "c", "name": "Stockage.mp4", "mimeType": "video/mp4", "driveId": "stockage",
             "createdTime": "2026-09-22T08:00:00Z"},
            {"id": "d", "name": "Visio Seyve.mp4", "mimeType": "video/mp4", "md5Checksum": "m2",
             "createdTime": "2026-09-20T08:00:00Z"},
        ]
        items = build_inventory(
            fichiers, user_id=1, shared_drives={}, recovered={},
            recovered_checksums={"m2": {"user_id": 2, "user_email": "luka@ekonum.fr", "job_id": 9}},
            library=[], excluded_drives={"stockage"},
        )
        par_id = {i["id"]: i for i in items}
        self.assertNotIn("c", par_id, "le stockage de transcript n'est pas une source")
        self.assertEqual(par_id["a"]["status"], "new")
        self.assertEqual((par_id["b"]["status"], par_id["b"]["duplicate_of"]), ("duplicate", "a"))
        self.assertEqual(par_id["d"]["status"], "recovered")
        self.assertEqual(par_id["d"]["recovered_by"], "luka@ekonum.fr")
        self.assertNotIn("job_id", par_id["d"], "la réunion d'un autre ne s'ouvre pas")


    def test_meme_nom_et_meme_taille_c_est_le_meme_fichier(self):
        """Drive recalcule parfois l'empreinte d'un fichier redéposé."""
        fichiers = [
            {"id": "a", "name": "Côte de Cambon 2.m4a", "mimeType": "audio/x-m4a", "size": "4963100",
             "md5Checksum": "m1", "createdTime": "2026-09-21T17:00:00Z"},
            {"id": "b", "name": "Côte de Cambon 2 (1).m4a", "mimeType": "audio/x-m4a", "size": "4963100",
             "md5Checksum": "m2", "createdTime": "2026-09-22T08:00:00Z"},
            {"id": "c", "name": "Côte de Cambon 2.m4a", "mimeType": "audio/x-m4a", "size": "5000000",
             "md5Checksum": "m3", "createdTime": "2026-09-23T08:00:00Z"},
            {"id": "d", "name": "Nouvel enregistrement.m4a", "mimeType": "audio/x-m4a", "size": "4663320",
             "md5Checksum": "m4", "createdTime": "2026-09-20T08:00:00Z"},
        ]
        items = build_inventory(
            fichiers, user_id=1, shared_drives={},
            recovered={"x": {"name": "Nouvel enregistrement.m4a", "size_bytes": 4663320, "user_id": 1,
                             "user_email": "robin@ekonum.fr", "job_id": 4}},
            recovered_checksums={}, library=[], excluded_drives=set(),
        )
        par_id = {i["id"]: i for i in items}
        self.assertEqual(par_id["a"]["status"], "new")
        self.assertEqual((par_id["b"]["status"], par_id["b"]["duplicate_of"]), ("duplicate", "a"))
        self.assertEqual(par_id["c"]["status"], "new", "même nom, autre taille : un autre enregistrement")
        self.assertEqual((par_id["d"]["status"], par_id["d"]["job_id"]), ("recovered", 4))


class FauxGoogle:
    """OAuth et Drive de Google, en mémoire, au niveau HTTP."""

    def __init__(self, email="robin@ekonum.fr"):
        self.email = email
        self.fichiers = {
            "f1": {"id": "f1", "name": "21 sept. à 18-34.m4a", "mimeType": "audio/x-m4a",
                   "size": "4", "md5Checksum": "m1", "createdTime": "2026-09-22T08:00:00Z",
                   "owners": [{"me": True, "emailAddress": "robin@ekonum.fr"}]},
            "f2": {"id": "f2", "name": "Tutoriel.mp4", "mimeType": "video/mp4", "size": "9",
                   "createdTime": "2026-09-10T08:00:00Z", "driveId": "d-ekonum"},
        }
        self.droits: dict[str, list[str]] = {}
        self.corbeille: list[str] = []
        self.appels: list[tuple[str, str]] = []
        self.revoques: list[str] = []

    def __call__(self, requete, timeout=None):
        url = urllib.parse.urlparse(requete.full_url)
        methode = requete.get_method()
        self.appels.append((methode, url.path))
        corps = requete.data.decode() if requete.data else ""
        if url.path == "/token":
            formulaire = dict(urllib.parse.parse_qsl(corps))
            if formulaire["grant_type"] == "authorization_code":
                return self._json({"access_token": "acces", "expires_in": 3600,
                                   "refresh_token": "rafraichissement", "scope": "drive",
                                   "id_token": _id_token(self.email)})
            return self._json({"access_token": "acces", "expires_in": 3600})
        if url.path == "/revoke":
            self.revoques.append(dict(urllib.parse.parse_qsl(corps))["token"])
            return self._json({})
        if url.path == "/drive/v3/drives":
            return self._json({"drives": [{"id": "d-ekonum", "name": "Ekonum"}]})
        if url.path == "/drive/v3/files" and methode == "GET":
            return self._json({"files": list(self.fichiers.values())})
        morceaux = url.path.split("/")
        file_id = morceaux[4] if len(morceaux) > 4 else ""
        if url.path.endswith("/permissions") and methode == "POST":
            self.droits.setdefault(file_id, []).append(json.loads(corps)["emailAddress"])
            return self._json({"id": "droit-1"})
        if "/permissions/" in url.path and methode == "DELETE":
            self.droits[file_id].pop()
            return self._json({})
        if methode == "PATCH":
            self.corbeille.append(file_id)
            return self._json({})
        if methode == "GET" and file_id in self.fichiers:
            return self._json(self.fichiers[file_id])
        raise urllib.error.HTTPError(requete.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))

    @staticmethod
    def _json(valeur):
        return io.BytesIO(json.dumps(valeur).encode())


class StockageAvecCopie(FauxStockage):
    """Le stockage, qui sait aussi copier un fichier du Drive de quelqu'un
    — à condition d'avoir été autorisé à le lire."""

    def __init__(self, google: FauxGoogle, compte: str):
        super().__init__()
        self.google = google
        self.compte = compte

    def copy_from(self, file_id, name):
        assert self.compte in self.google.droits.get(file_id, []), "copie sans droit de lecture"
        taille = int(self.google.fichiers[file_id]["size"])
        nouvel_id = f"copie-{file_id}"
        self.fichiers[nouvel_id] = b"x" * taille
        return {"id": nouvel_id, "size": str(taille)}


class RecoveryApiTestCase(unittest.TestCase):
    COMPTE = "transcript-stockage@transcript-509912.iam.gserviceaccount.com"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.settings = _settings(root, google_client_id="client-id", gcp_compte=self.COMPTE,
                                  recovery_users=frozenset({"robin@ekonum.fr"}))
        self.db = Database(self.settings.db_path)
        self.google = FauxGoogle()
        self.stockage = StockageAvecCopie(self.google, self.COMPTE)
        # Le secret du client vient du coffre : on le double avant que
        # l'application ne capture son lecteur.
        import app.secrets as secrets_module
        origine = secrets_module.GeminiKey.get
        self.addCleanup(setattr, secrets_module.GeminiKey, "get", origine)
        secrets_module.GeminiKey.get = lambda self_: "secret-du-client"
        self.app = create_app(
            self.settings, database=self.db,
            gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
            stockage_factory=lambda: self.stockage,
            google_opener=self.google,
        )
        self.client = _Client(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def _connecter(self):
        depart = self.client.get("/api/google/connect", follow_redirects=False)
        self.assertEqual(depart.status_code, 302)
        cible = urllib.parse.urlparse(depart.headers["location"])
        parametres = dict(urllib.parse.parse_qsl(cible.query))
        return self.client.get(
            "/api/google/callback", params={"state": parametres["state"], "code": "code"},
            follow_redirects=False,
        ), parametres

    def test_la_connexion_demande_hors_ligne_avec_pkce_et_le_domaine(self):
        retour, parametres = self._connecter()
        self.assertEqual(parametres["code_challenge_method"], "S256")
        self.assertEqual(parametres["access_type"], "offline")
        self.assertEqual(parametres["hd"], "ekonum.fr")
        self.assertEqual(parametres["login_hint"], "robin@ekonum.fr")
        self.assertIn("auth/drive", parametres["scope"])
        self.assertEqual(retour.headers["location"], "/?recovery=connected")
        etat = self.client.get("/api/google").json()
        self.assertEqual((etat["connected"], etat["email"]), (True, "robin@ekonum.fr"))
        # Le jeton de rafraîchissement est chiffré en base.
        self.assertNotIn("rafraichissement", self.db.google_account(1)["refresh_token_enc"])

    def test_un_etat_inconnu_ou_deja_servi_ne_connecte_rien(self):
        retour = self.client.get("/api/google/callback", params={"state": "invente", "code": "c"},
                                 follow_redirects=False)
        self.assertEqual(retour.headers["location"], "/?recovery=expired")
        self.assertFalse(self.client.get("/api/google").json()["connected"])

    def test_le_drive_d_un_autre_compte_est_refuse_et_revoque(self):
        self.google.email = "izaak@ekonum.fr"
        retour, _ = self._connecter()
        self.assertEqual(retour.headers["location"], "/?recovery=wrong_account")
        self.assertFalse(self.client.get("/api/google").json()["connected"])
        self.assertEqual(self.google.revoques, ["rafraichissement"])

    def test_inventaire_puis_recuperation_sans_doublon(self):
        self._connecter()
        items = {i["id"]: i for i in self.client.get("/api/recovery/drive").json()["items"]}
        self.assertEqual(items["f1"]["kind"], "meeting")
        self.assertEqual(items["f1"]["recorded_at"], "2026-09-21T18:34")
        self.assertEqual(items["f2"]["kind"], "other")
        self.assertEqual(items["f2"]["location"], {"kind": "shared_drive", "name": "Ekonum"})

        vue = self.client.post("/api/recovery/drive/f1", json={"trash_original": True}).json()
        self.assertEqual(vue["original"], "trashed")
        self.assertEqual(self.google.corbeille, ["f1"])
        # Le droit de lecture du compte de service n'a duré que la copie.
        self.assertEqual(self.google.droits["f1"], [])
        fiche = self.client.get(f"/api/jobs/{vue['job_id']}/detail").json()
        self.assertEqual(fiche["status"], "recovered")
        self.assertEqual(fiche["meeting_date"][:16], "2026-09-21T18:34")
        self.assertTrue(fiche["video"]["presente"])

        # Relancer ne récupère pas deux fois, et l'inventaire le montre.
        self.assertEqual(self.client.post("/api/recovery/drive/f1", json={}).status_code, 409)
        apres = {i["id"]: i for i in self.client.get("/api/recovery/drive").json()["items"]}
        self.assertEqual(apres["f1"]["status"], "recovered")
        self.assertEqual(apres["f1"]["job_id"], vue["job_id"])

    def _reunion_deja_transcrite(self, owner_id=1):
        job_id = self.db.create_job(
            owner_id=owner_id, filename="21 sept. à 18-34.m4a", duration_seconds=1800, model="",
            language="fr", context={}, chunks=[],
        )
        self.db.set_meeting_date(job_id, "2026-09-21T18:34")
        return job_id

    def test_ranger_avec_la_reunion_existante_plutot_qu_en_creer_une(self):
        self._connecter()
        job_id = self._reunion_deja_transcrite()
        item = {i["id"]: i for i in self.client.get("/api/recovery/drive").json()["items"]}["f1"]
        self.assertEqual((item["status"], item["job_id"]), ("in_library", job_id))

        vue = self.client.post("/api/recovery/drive/f1/attach",
                               json={"job_id": job_id, "trash_original": True}).json()
        self.assertEqual((vue["job_id"], vue["video"], vue["original"]), (job_id, "attached", "trashed"))
        self.assertEqual(self.google.droits["f1"], [])
        self.assertTrue(self.client.get(f"/api/jobs/{job_id}/detail").json()["video"]["presente"])
        self.assertEqual(self.client.get("/api/jobs").headers["x-total-count"], "1", "pas de seconde réunion")
        apres = {i["id"]: i for i in self.client.get("/api/recovery/drive").json()["items"]}["f1"]
        self.assertEqual((apres["status"], apres["job_id"]), ("recovered", job_id))
        self.assertEqual(self.client.post("/api/recovery/drive/f1/attach",
                                          json={"job_id": job_id}).status_code, 409)

    def test_une_reunion_qui_a_deja_sa_video_garde_l_original_s_il_differe(self):
        self._connecter()
        job_id = self._reunion_deja_transcrite()
        self.db.ouvrir_envoi_video(job_id, "", 99)
        self.db.terminer_envoi_video(job_id, "video-mac")
        vue = self.client.post("/api/recovery/drive/f1/attach",
                               json={"job_id": job_id, "trash_original": True}).json()
        self.assertEqual((vue["video"], vue["original"]), ("kept", "kept_different"))
        self.assertEqual(self.google.corbeille, [])
        self.assertEqual(self.db.get_job(job_id)["video_file_id"], "video-mac")

    def test_on_ne_range_pas_avec_la_reunion_d_un_autre(self):
        self._connecter()
        autre = self._reunion_deja_transcrite(owner_id=self.db.user_id_for_email("luka@ekonum.fr"))
        reponse = self.client.post("/api/recovery/drive/f1/attach", json={"job_id": autre})
        self.assertEqual(reponse.status_code, 404)
        self.assertEqual(self.google.corbeille, [])

    def test_sans_retrait_demande_l_original_reste(self):
        self._connecter()
        vue = self.client.post("/api/recovery/drive/f1", json={"trash_original": False}).json()
        self.assertEqual(vue["original"], "not_requested")
        self.assertEqual(self.google.corbeille, [])

    def test_l_invitation_ne_revient_pas_une_fois_ecartee(self):
        self.assertTrue(self.client.get("/api/recovery").json()["prompt"])
        self.client.post("/api/recovery/dismiss")
        self.assertFalse(self.client.get("/api/recovery").json()["prompt"])

    def test_fermee_a_qui_n_est_pas_dans_la_liste(self):
        """On l'éprouve avant de l'ouvrir : hors liste, ni invitation, ni
        route."""
        autre = create_app(
            _settings(Path(self._tmp.name), google_client_id="client-id", dev_user_email="luka@ekonum.fr",
                      recovery_users=frozenset({"robin@ekonum.fr"})),
            database=self.db,
            gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
            stockage_factory=lambda: self.stockage, google_opener=self.google,
        )
        with _Client(autre) as client:
            self.assertEqual(client.get("/api/recovery").json(), {"enabled": False, "prompt": False})
            self.assertEqual(client.get("/api/recovery/drive").status_code, 404)
            self.assertEqual(client.get("/api/google/connect", follow_redirects=False).status_code, 404)

    def test_sans_secret_lisible_pas_d_invitation(self):
        import app.secrets as secrets_module

        def absent(self_):
            raise secrets_module.SecretError("élément absent")

        secrets_module.GeminiKey.get = absent
        etat = self.client.get("/api/recovery").json()
        self.assertFalse(etat["google"]["available"])
        self.assertFalse(etat["prompt"])

    def test_se_deconnecter_revoque_chez_google(self):
        self._connecter()
        self.assertEqual(self.client.delete("/api/google").status_code, 204)
        self.assertFalse(self.client.get("/api/google").json()["connected"])
        self.assertIn("rafraichissement", self.google.revoques)


if __name__ == "__main__":
    unittest.main()
