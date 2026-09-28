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
        return self._poster_en_html(
            modele, record_id, corps_html, subtype="mail.mt_note"
        )

    def _poster_en_html(
        self,
        modele: str,
        record_id: int,
        corps_html: str,
        *,
        subtype: str,
        extra: dict[str, Any] | None = None,
    ) -> int:
        """Poste, retrouve, puis réécrit — le seul chemin qui laisse du
        HTML s'afficher.

        ``message_post`` échappe le corps quoi qu'on fasse. On sème donc
        un marqueur, on retrouve le message par ce marqueur, et on
        réécrit le corps tel qu'il doit s'afficher. Vaut pour une note
        de chatter comme pour un ping : c'est la même API, donc le même
        piège.
        """
        marqueur = f"<!-- transcript:{record_id}:{abs(hash(corps_html)) % 10**12} -->"
        self._appel(
            modele,
            "message_post",
            {
                "ids": [record_id],
                "body": corps_html + marqueur,
                "message_type": "comment",
                "subtype_xmlid": subtype,
                **(extra or {}),
            },
        )
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
                "Le message a été posté mais reste introuvable : son corps n'a "
                "pas pu être remis en forme."
            )
        message_id = int(trouves[0]["id"])
        self._appel(
            "mail.message", "write", {"ids": [message_id], "vals": {"body": corps_html}}
        )
        return message_id


    # ------------------------------------------------------------------
    # Prévenir : le travail est fait, ou il demande un regard.
    # ------------------------------------------------------------------

    # Partenaire d'OdooBot : `base.partner_root`, id 2 dans toute base
    # Odoo. Il est archivé (`active = False`), ce qui le rend invisible
    # aux recherches — d'où l'identifiant en dur plutôt qu'un
    # `search_read` qui renverrait toujours vide.
    BOT = 2

    def canal_prive(self, partner_id: int) -> int | None:
        """La conversation OdooBot de cette personne, si elle existe."""
        canaux = self._appel(
            "discuss.channel",
            "search_read",
            {
                "domain": [
                    ["channel_type", "=", "chat"],
                    ["channel_member_ids.partner_id", "=", int(partner_id)],
                    ["channel_member_ids.partner_id", "=", self.BOT],
                ],
                "fields": ["id"],
                "limit": 1,
            },
        )
        return int(canaux[0]["id"]) if canaux else None

    def prevenir(self, partner_id: int, texte_html: str) -> int | None:
        """Ping dans la conversation OdooBot. Rend l'identifiant du
        message, ou ``None`` si la personne n'a pas cette conversation.

        Le message est signé **OdooBot**, pas la personne : un message
        qu'on s'écrit à soi-même ne déclenche aucune notification, donc
        ne prévient personne.
        """
        canal = self.canal_prive(partner_id)
        if canal is None:
            return None
        try:
            return self._poster_en_html(
                "discuss.channel", canal, texte_html,
                subtype="mail.mt_comment", extra={"author_id": self.BOT},
            )
        except ChatterError:
            # Une base qui refuse d'écrire au nom d'OdooBot vaut mieux
            # qu'un silence : on signe de la personne et on prévient
            # quand même.
            return self._poster_en_html(
                "discuss.channel", canal, texte_html, subtype="mail.mt_comment"
            )

    def activite(
        self, modele: str, record_id: int, user_id: int, resume: str, note: str = ""
    ) -> int | None:
        """Repli : une activité sur le dossier, à défaut de conversation.

        Moins direct qu'un ping, mais ça atterrit dans la liste des
        choses à faire — donc ça ne se perd pas.
        """
        modeles = self._appel(
            "ir.model", "search_read",
            {"domain": [["model", "=", modele]], "fields": ["id"], "limit": 1},
        )
        if not modeles:
            return None
        types = self._appel(
            "mail.activity.type", "search_read",
            {"domain": [["category", "=", "default"]], "fields": ["id"], "limit": 1},
        )
        return _identifiant(
            self._appel(
                "mail.activity",
                "create",
                {
                    "vals_list": [
                        {
                            "res_model_id": int(modeles[0]["id"]),
                            "res_id": int(record_id),
                            "user_id": int(user_id),
                            "summary": resume[:200],
                            "note": note,
                            **({"activity_type_id": int(types[0]["id"])} if types else {}),
                        }
                    ]
                },
            )
        )


def _identifiant(reponse: Any) -> int | None:
    """Odoo rend tantôt un entier, tantôt une liste, tantôt un dict."""
    if isinstance(reponse, int):
        return reponse
    if isinstance(reponse, list) and reponse:
        return _identifiant(reponse[0])
    if isinstance(reponse, dict):
        for cle in ("id", "message_id"):
            if isinstance(reponse.get(cle), int):
                return int(reponse[cle])
    return None


def deja_publie(corps: str) -> bool:
    """Un accordéon est-il déjà présent ? Sert à ne pas empiler."""
    return bool(re.search(r"<details", corps or "", re.IGNORECASE))
