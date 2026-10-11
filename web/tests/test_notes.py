"""Les transcriptions collées dans Odoo : lecture, et récupération."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app as _app_package  # noqa: F401  (installe la racine du dépôt dans sys.path)

from app.db import Database
from app.main import create_app
from app.notes import fingerprint, html_text, overlap, read_note, segments, split_note
from app.odoo import OdooUnavailable
from app.secrets import GeminiKey
from app.transcription import transcript_text
from tests.test_api import FauxStockage, _Client, _settings
from tests.test_recovery import FausseOdoo

# Une réunion assez longue pour avoir une empreinte : chaque réplique
# porte ses propres mots.
REPLIQUES = [
    ("Robin", "Bonjour à tous, on commence par le point sur la mairie de Cambon et son projet de rénovation."),
    ("Muriel", "Oui, le conseil municipal a voté le budget mardi dernier, avec une enveloppe de quarante mille euros."),
    ("Robin", "Très bien, il faudra prévoir la visite technique avant la fin du mois pour chiffrer les travaux."),
    ("Muriel", "Je propose le jeudi matin, le maire sera présent et pourra nous montrer les bâtiments concernés."),
    ("Robin", "Parfait, j'envoie le compte rendu demain et je relance le bureau d'études pour les plans."),
]


def html_note(titre="Transcription complète", entete="Appel du 2 décembre"):
    """Le format de l'app macOS : du HTML, une réplique par paragraphe."""
    lignes = "".join(f"<p>[{nom}] (00:0{i}:00) {texte}</p>" for i, (nom, texte) in enumerate(REPLIQUES))
    return (f"<p>{entete}</p><details><summary>{titre} (cliquer pour dérouler)</summary>"
            f"<div>{lignes}</div></details>")


def texte_note():
    """Le format de transcript : du texte brut dans un cadre pre-wrap."""
    lignes = "\n".join(f"{nom} : {texte}" for nom, texte in REPLIQUES)
    return ('<details><summary>Transcription complète (cliquer pour dérouler)</summary>'
            f'<div style="white-space: pre-wrap">{lignes}</div></details>')


class ParsingTestCase(unittest.TestCase):
    def test_le_format_html_et_ses_horodatages(self):
        note = read_note({"body": html_note(titre="Point Cambon"), "record_name": "Mairie de Cambon"})
        self.assertEqual(note["title"], "Point Cambon")
        self.assertEqual(note["header"], "Appel du 2 décembre")
        self.assertEqual(note["kind"], "meeting")
        self.assertEqual([s["speaker"] for s in note["segments"]], [n for n, _ in REPLIQUES])
        self.assertEqual([s["start"] for s in note["segments"]], [0, 60, 120, 180, 240])
        self.assertEqual(note["segments"][0]["end"], 60)

    def test_le_format_texte_sans_horodatage(self):
        note = read_note({"body": texte_note(), "record_name": "Mairie de Cambon"})
        self.assertEqual(note["title"], "Mairie de Cambon", "le titre générique cède la place à la fiche")
        self.assertEqual(note["header"], "")
        self.assertEqual(len(note["segments"]), 5)
        self.assertTrue(all(s["start"] == 0 for s in note["segments"]))
        self.assertEqual(note["segments"][1]["text"], REPLIQUES[1][1])

    def test_un_nom_qui_ne_revient_pas_n_est_pas_un_interlocuteur(self):
        repliques = segments("Voici l'appel.\nFeedback : bon\nRobin : bonjour\nIl m'a dit : non\n"
                             "Charles : oui\nRobin : bon\nCharles : d'accord")
        self.assertEqual([r["speaker"] for r in repliques], ["", "", "Robin", "Charles", "Robin", "Charles"])
        self.assertEqual(repliques[1]["text"], "Feedback : bon", "avant la première réplique, des lignes")
        self.assertEqual(repliques[2]["text"], "bonjour Il m'a dit : non")

    def test_des_lignes_coupees_et_plusieurs_repliques_par_ligne(self):
        repliques = segments("Robin : Je vous entends pas. Est-ce que c'est mes écouteurs\npar hasard ? "
                             "Martin : Oui. Robin\n(Ekonum) : Top. Robin (Ekonum) : Bon.\n00:33\nMartin : Non. Robin : Fin.")
        self.assertEqual([(r["speaker"], r["text"]) for r in repliques], [
            ("Robin", "Je vous entends pas. Est-ce que c'est mes écouteurs par hasard ?"),
            ("Martin", "Oui."), ("Robin (Ekonum)", "Top."), ("Robin (Ekonum)", "Bon."), ("Martin", "Non."),
            ("Robin", "Fin."),
        ])
        self.assertEqual(repliques[-2]["start"], 33)

    def test_les_autres_facons_d_annoncer_une_replique(self):
        texte = ("**Robin JOSEPH** : Bonjour.\n**Marie FABRE** : Oui.\n**Robin JOSEPH** : Bien.\n**Marie FABRE** : OK.\n"
                 "Jean-Nicolas [00:31]\nEuh, et donc.\nJean-Nicolas [00:37]\nVoilà.\n"
                 "François (00:10 - 01:00) : Moi ça va.\nFrançois (01:00 - 01:30) : Donc.\n"
                 "00:31 – Luca Marin (Odoo) : Bonjour.\n00:32 – Luca Marin (Odoo) : Re.")
        repliques = segments(texte)
        self.assertEqual([r["speaker"] for r in repliques], ["Robin JOSEPH", "Marie FABRE"] * 2
                         + ["Jean-Nicolas"] * 2 + ["François"] * 2 + ["Luca Marin (Odoo)"] * 2)
        self.assertEqual([r["start"] for r in repliques][4:], [31, 37, 10, 60, 31, 32])
        self.assertEqual(repliques[4]["text"], "Euh, et donc.")

    def test_un_nom_seul_sur_sa_ligne(self):
        repliques = segments("Muriel :\nBonjour.\nRobin :\nSalut.\nMuriel : Ça va ?\nRobin : Oui.")
        self.assertEqual([(r["speaker"], r["text"]) for r in repliques][:2],
                         [("Muriel", "Bonjour."), ("Robin", "Salut.")])

    def test_un_courriel_n_est_pas_une_reunion(self):
        corps = ('<details><summary>Transcription complète (cliquer pour dérouler)</summary>'
                 '<pre>De : Robin\nÀ : Muriel\nObjet : devis</pre></details>')
        self.assertEqual(read_note({"body": corps})["kind"], "other")

    def test_le_cadre_et_les_balises(self):
        _, _, contenu = split_note('<details><summary>x</summary><div style="a">un<br>deux</div></details>')
        self.assertEqual(html_text(contenu), "un\ndeux")
        self.assertEqual(html_text("a&nbsp;b\n<pre>c\nd</pre>"), "a b\nc\nd")

    def test_l_empreinte_reconnait_le_meme_texte_reformate(self):
        a = read_note({"body": html_note()})["fingerprint"]
        b = read_note({"body": texte_note()})["fingerprint"]
        self.assertTrue(a)
        self.assertGreaterEqual(overlap(a, b), 0.9)
        self.assertLess(overlap(a, fingerprint("une tout autre réunion " * 40 + " ".join(map(str, range(400))))), 0.25)


class FausseOdooNotes(FausseOdoo):
    def __init__(self, cle="cle"):
        super().__init__(cle)
        self.notes = {
            901: {"id": 901, "model": "crm.lead", "res_id": 640, "record_name": "Mairie de Cambon",
                  "date": "2025-12-02 09:30:00", "author_id": [3, "SAS Ekonum, Robin"], "body": html_note()},
            902: {"id": 902, "model": "crm.lead", "res_id": 641, "record_name": "Mairie de Cambon (bis)",
                  "date": "2025-12-03 10:00:00", "author_id": [4, "SAS Ekonum, Muriel"], "body": texte_note()},
            903: {"id": 903, "model": "project.project", "res_id": 5, "record_name": "Site web",
                  "date": "2025-11-01 08:00:00", "author_id": [3, "SAS Ekonum, Robin"],
                  "body": '<details><summary>Transcription complète (cliquer pour dérouler)</summary>'
                          '<pre>From: client\nTo: Robin\nMerci pour le devis</pre></details>'},
        }

    def transcript_notes(self, limit=1000):
        return list(self.notes.values())

    def transcript_note(self, message_id):
        if message_id not in self.notes:
            raise OdooUnavailable("Note introuvable dans Odoo.")
        return self.notes[message_id]


class NotesApiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings = _settings(Path(self._tmp.name), odoo_url="https://ekonum.odoo.com",
                                  recovery_users=frozenset({"robin@ekonum.fr"}))
        self.db = Database(self.settings.db_path)
        self.odoo = FausseOdooNotes()
        self.app = create_app(
            self.settings, database=self.db,
            gemini_key=GeminiKey(url="", token="", item="", field="", static_key="k"),
            stockage_factory=lambda: FauxStockage(),
            odoo_factory=lambda _owner: self.odoo,
        )
        self.client = _Client(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.moi = self.db.user_id_for_email("robin@ekonum.fr")

    def _items(self):
        retour = self.client.get("/api/recovery/odoo-notes")
        self.assertEqual(retour.status_code, 200, retour.text)
        return {i["id"]: i for i in retour.json()["items"]}

    def _reunion(self, owner_id, repliques=REPLIQUES):
        job_id = self.db.create_job(owner_id=owner_id, filename="cambon.m4a", duration_seconds=600,
                                    model="gemini", language="fr", context={}, chunks=[])
        segs = [{"start": i * 60.0, "end": i * 60.0 + 60, "speaker": n, "text": t}
                for i, (n, t) in enumerate(repliques)]
        self.db.replace_segments(job_id, segs)
        self.db.finish_job(job_id, title="Cambon", transcript=transcript_text(segs), speakers={},
                           technical_terms=[], cost_usd=0.1)
        return job_id

    def test_l_inventaire(self):
        items = self._items()
        self.assertEqual(list(items), ["902", "901", "903"], "du plus récent au plus ancien")
        self.assertEqual(items["901"]["status"], "new")
        self.assertEqual(items["902"]["status"], "duplicate", "la même réunion collée deux fois")
        self.assertEqual(items["902"]["duplicate_of"], "901")
        self.assertEqual(items["901"]["author"], "Robin")
        self.assertEqual(items["901"]["excerpt"], "Appel du 2 décembre")
        self.assertEqual(items["901"]["recorded_at"], "2025-12-02T10:30", "Odoo date en UTC")
        self.assertEqual(items["901"]["location"]["name"], "opportunité · Mairie de Cambon")
        self.assertEqual(items["901"]["web_link"], "https://ekonum.odoo.com/odoo/crm.lead/640")
        self.assertEqual(items["903"]["kind"], "other")

    def test_recuperer_une_note(self):
        vue = self.client.post("/api/recovery/odoo-notes/901").json()
        self.assertEqual((vue["original"], vue["linked"]), ("left_in_odoo", True))
        fiche = self.client.get(f"/api/jobs/{vue['job_id']}/detail").json()
        self.assertEqual(fiche["status"], "termine")
        self.assertEqual(fiche["meeting_date"], "2025-12-02T10:30")
        self.assertEqual([s["speaker"] for s in fiche["segments"]], [n for n, _ in REPLIQUES])
        self.assertEqual((fiche["odoo"]["model"], fiche["odoo"]["record_id"], fiche["odoo"]["message_id"]),
                         ("crm.lead", 640, 901))
        self.assertTrue(fiche["odoo"]["published_at"], "déjà dans Odoo : transcript ne la redéposera pas")

        # Jamais deux fois : ni la même note, ni sa copie.
        self.assertEqual(self.client.post("/api/recovery/odoo-notes/901").status_code, 409)
        self.assertEqual(self.client.post("/api/recovery/odoo-notes/902").status_code, 409)
        items = self._items()
        self.assertEqual((items["901"]["status"], items["901"]["job_id"]), ("recovered", vue["job_id"]))
        self.assertEqual((items["902"]["status"], items["902"]["job_id"]), ("in_library", vue["job_id"]))
        self.assertEqual(self.client.get("/api/jobs").headers["x-total-count"], "1")

    def test_une_note_sans_texte(self):
        self.odoo.notes[904] = {**self.odoo.notes[901], "id": 904,
                                "body": "<details><summary>Transcription complète</summary><div></div></details>"}
        self.assertEqual(self.client.post("/api/recovery/odoo-notes/904").status_code, 422)
        self.assertEqual(self.client.get("/api/jobs").headers["x-total-count"], "0")

    def test_une_note_deposee_par_transcript(self):
        job_id = self._reunion(self.moi)
        self.db.set_odoo_link(job_id, model="crm.lead", record_id=640, message_id=901)
        items = self._items()
        self.assertEqual((items["901"]["status"], items["901"]["job_id"]), ("published", job_id))
        self.assertEqual(self.client.post("/api/recovery/odoo-notes/901").status_code, 409)

    def test_relier_une_note_a_ma_reunion(self):
        job_id = self._reunion(self.moi)
        items = self._items()
        self.assertEqual((items["901"]["status"], items["901"]["job_id"]), ("in_library", job_id))
        vue = self.client.post("/api/recovery/odoo-notes/901/attach", json={"job_id": job_id}).json()
        self.assertEqual((vue["job_id"], vue["video"], vue["linked"]), (job_id, "kept", True))
        fiche = self.client.get(f"/api/jobs/{job_id}/detail").json()
        self.assertEqual((fiche["odoo"]["model"], fiche["odoo"]["message_id"]), ("crm.lead", 901))
        self.assertEqual(self.client.get("/api/jobs").headers["x-total-count"], "1", "pas de seconde réunion")
        self.assertEqual(self._items()["901"]["status"], "recovered")

    def test_on_ne_relie_pas_une_autre_reunion(self):
        autre = self._reunion(self.moi, [("A", "rien à voir " * 3 + " ".join(map(str, range(200))))])
        retour = self.client.post("/api/recovery/odoo-notes/901/attach", json={"job_id": autre})
        self.assertEqual(retour.status_code, 409)

    def test_une_reunion_deja_liee_garde_sa_fiche(self):
        job_id = self._reunion(self.moi)
        self.db.set_odoo_link(job_id, model="project.project", record_id=3, message_id=None)
        vue = self.client.post("/api/recovery/odoo-notes/901/attach", json={"job_id": job_id}).json()
        self.assertFalse(vue["linked"])
        fiche = self.client.get(f"/api/jobs/{job_id}/detail").json()
        self.assertEqual((fiche["odoo"]["model"], fiche["odoo"]["record_id"]), ("project.project", 3))

    def test_la_reunion_d_un_collegue(self):
        luka = self.db.user_id_for_email("luka@ekonum.fr")
        job_id = self._reunion(luka)
        items = self._items()
        self.assertEqual(items["901"]["status"], "colleague")
        self.assertEqual(items["901"]["recovered_by"], "luka@ekonum.fr")
        self.assertNotIn("job_id", items["901"])
        self.assertEqual(self.client.post("/api/recovery/odoo-notes/901").status_code, 409)
        self.assertEqual(self.client.post("/api/recovery/odoo-notes/901/attach",
                                          json={"job_id": job_id}).status_code, 404)

    def test_une_reunion_modifiee_est_relue(self):
        job_id = self._reunion(self.moi)
        self.assertEqual(self._items()["901"]["status"], "in_library")
        self.db.supprimer_job(job_id)
        self.assertEqual(self._items()["901"]["status"], "new")

    def test_l_ordre_des_repliques_sans_horodatage(self):
        vue = self.client.post("/api/recovery/odoo-notes/902").json()
        fiche = self.client.get(f"/api/jobs/{vue['job_id']}/detail").json()
        self.assertEqual([s["text"] for s in fiche["segments"]], [t for _, t in REPLIQUES])

    def test_sans_cle_odoo(self):
        self.odoo = FausseOdooNotes(cle="")
        self.assertEqual(self.client.get("/api/recovery/odoo-notes").status_code, 409)


if __name__ == "__main__":
    unittest.main()
