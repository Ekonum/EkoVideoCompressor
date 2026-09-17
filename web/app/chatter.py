"""Dépôt d'une transcription dans le chatter Odoo.

Le gabarit et les contournements viennent du chantier du 14 septembre,
où il a fallu replier 108 messages et assainir 10 opportunités dont les
descriptions avaient enflé jusqu'à 302 000 caractères. Ce travail-là
n'était pas versionné : il l'est ici, et il s'applique désormais **à
l'écriture** plutôt qu'après coup.

Deux pièges, tous deux rencontrés en production :

* ``message_post`` **échappe le HTML**. On poste, puis on réécrit le
  corps par ``mail.message.write`` — c'est le seul chemin qui laisse un
  accordéon déroulable.
* Un composant OWL est impossible dans le chatter, qui désactive les
  composants embarqués. D'où l'accordéon HTML5 ``<details>``, validé
  contre le nettoyeur HTML d'Odoo.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from typing import Any

UA = "transcript-chatter/1.0"

# Repris tel quel du chantier : les classes sont celles du thème Odoo, et
# la hauteur bornée évite de rendre le chatter illisible — c'était le
# problème d'origine.
GABARIT = """<details class="border rounded p-2 my-2 bg-light">
  <summary class="fw-bold text-primary" style="cursor: pointer;">
    <i class="oi oi-subtitle me-1"></i> {titre} (cliquer pour dérouler)
  </summary>
  <div style="max-height: 380px; overflow-y: auto; white-space: pre-wrap; \
font-size: 0.85rem; line-height: 1.4;" class="border-top pt-2 mt-2 text-muted">
{corps}
  </div>
</details>"""


class ChatterError(RuntimeError):
    """Le dépôt a échoué — message destiné à l'utilisateur."""


def composer(titre: str, transcript: str, *, entete: str = "") -> str:
    """Assemble la note : un en-tête lisible, puis l'accordéon.

    L'en-tête reste **hors** de l'accordéon : c'est lui qu'on lit en
    parcourant le chatter, et le replier rendrait la note muette.
    """
    corps = html.escape(transcript or "", quote=False)
    bloc = GABARIT.format(titre=html.escape(titre or "Transcription complète"), corps=corps)
    return f"<p>{html.escape(entete)}</p>{bloc}" if entete else bloc


class OdooChatter:
    """Client JSON-2 minimal, limité à ce que le dépôt demande."""

    def __init__(self, base_url: str, api_key: str, *, opener=None) -> None:
        self._base = (base_url or "").rstrip("/")
        self._key = api_key
        self._opener = opener or urllib.request.urlopen

    def _appel(self, modele: str, methode: str, charge: dict) -> Any:
        url = f"{self._base}/json/2/{modele}/{methode}"
        requete = urllib.request.Request(
            url,
            data=json.dumps(charge, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                # Sans User-Agent réel, Cloudflare répond 403 error code
                # 1010, qui ressemble à s'y méprendre à un refus d'auth.
                "User-Agent": UA,
            },
        )
        try:
            with self._opener(requete, timeout=120) as reponse:
                brut = reponse.read().decode("utf-8") or "null"
        except urllib.error.HTTPError as exc:
            raise ChatterError(
                f"Odoo a refusé {modele}.{methode} (HTTP {exc.code})."
            ) from exc
        except urllib.error.URLError as exc:
            raise ChatterError(f"Odoo injoignable : {exc.reason}.") from exc
        return json.loads(brut)

    def publier(self, modele: str, record_id: int, corps_html: str) -> int:
        """Poste une note interne et rend son identifiant.

        Note interne (`mail.mt_note`) et non message : déposer une
        transcription de réunion ne doit pas déclencher un e-mail aux
        abonnés du dossier.
        """
        marqueur = f"<!-- transcript:{record_id}:{abs(hash(corps_html)) % 10**12} -->"
        self._appel(
            modele,
            "message_post",
            {
                "ids": [record_id],
                "body": corps_html + marqueur,
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_note",
            },
        )

        # message_post échappe le HTML : on retrouve le message par son
        # marqueur, puis on réécrit le corps tel qu'il doit s'afficher.
        trouves = self._appel(
            "mail.message",
            "search_read",
            {
                "domain": [
                    ["model", "=", modele],
                    ["res_id", "=", record_id],
                    ["body", "ilike", marqueur[4:24]],
                ],
                "fields": ["id"],
                "limit": 1,
                "order": "id desc",
            },
        )
        if not trouves:
            raise ChatterError(
                "La note a été postée mais reste introuvable : son corps n'a "
                "pas pu être remis en forme."
            )
        message_id = int(trouves[0]["id"])
        self._appel(
            "mail.message", "write", {"ids": [message_id], "vals": {"body": corps_html}}
        )
        return message_id


def deja_publie(corps: str) -> bool:
    """Un accordéon est-il déjà présent ? Sert à ne pas empiler."""
    return bool(re.search(r"<details", corps or "", re.IGNORECASE))
