"""Accès Odoo, côté serveur.

`odoo_client.py` est repris tel quel — il est en stdlib pur et connaît
déjà le JSON-2, la recherche de réunions, le pack de contexte et
l'extraction de noms propres. Ce module ne fait que deux choses que le
moteur macOS n'avait pas à faire : lire les identifiants dans le broker
plutôt que dans les réglages d'une app, et ne jamais laisser une panne
Odoo faire échouer une transcription.

Ce dernier point est le vrai parti pris : Odoo enrichit, il ne
conditionne pas. Une réunion doit se transcrire même si le serveur Odoo
est en maintenance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from odoo_client import (
    OdooConfig,
    OdooError,
    extract_company_name_from_pack,
    extract_odoo_glossary_candidates,
    fetch_related_context_pack,
    search_meeting_events,
)

log = logging.getLogger("ekovideo.web")


class OdooUnavailable(RuntimeError):
    """Odoo est injoignable ou mal configuré — message pour l'utilisateur."""


class OdooGateway:
    """Charge les identifiants une fois, puis sert les appels."""

    def __init__(self, secrets, *, url: str, database: str, login: str) -> None:
        self._secrets = secrets
        self._url = url
        self._database = database
        self._login = login

    @property
    def configured(self) -> bool:
        return bool(self._url and self._database and self._login)

    def _config(self) -> OdooConfig:
        if not self.configured:
            raise OdooUnavailable(
                "Odoo n'est pas configuré (URL, base et identifiant). "
                "Les suggestions de réunion sont désactivées."
            )
        return OdooConfig(
            url=self._url,
            database=self._database,
            login=self._login,
            api_key=self._secrets.get(),
        )

    def meetings(self, *, near: datetime | None = None, window_hours: float = 2.0) -> list[dict]:
        """Réunions qui encadrent un instant donné.

        Sert à proposer « c'est sans doute cette réunion-là » au moment
        où l'utilisateur dépose un enregistrement.
        """
        moment = near or datetime.now(timezone.utc)
        try:
            events = search_meeting_events(self._config(), near=moment, window_hours=window_hours)
        except OdooError as exc:
            raise OdooUnavailable(str(exc)) from exc
        return [
            {
                "id": event.get("id"),
                "name": event.get("name") or "",
                "start": event.get("start") or "",
                "stop": event.get("stop") or "",
                "attendees": [a.get("name") for a in event.get("attendees") or [] if a.get("name")],
                "resource_model": event.get("res_model") or "",
                "resource_id": event.get("res_id") or 0,
            }
            for event in events
        ]

    def search_records(self, terme: str, limit: int = 8) -> list[dict[str, Any]]:
        """Cherche un dossier où déposer la transcription.

        Limité aux opportunités pour l'instant : c'est de loin le cas le
        plus fréquent, et ouvrir d'emblée à tous les modèles rendrait la
        liste illisible avant qu'on sache la classer (jalon M8.3).
        """
        requete = (terme or "").strip()
        if len(requete) < 2:
            return []
        from odoo_client import _json2_call  # client JSON-2 déjà éprouvé

        try:
            lignes = _json2_call(
                self._config(),
                "crm.lead",
                "search_read",
                {
                    "domain": ["|", ["name", "ilike", requete],
                               ["partner_id.name", "ilike", requete]],
                    "fields": ["name", "partner_id", "write_date"],
                    "limit": limit,
                    "order": "write_date desc",
                },
            )
        except OdooError as exc:
            raise OdooUnavailable(str(exc)) from exc

        return [
            {
                "model": "crm.lead",
                "id": l.get("id"),
                "name": l.get("name") or "",
                "partner": (l.get("partner_id") or [None, ""])[1]
                if isinstance(l.get("partner_id"), list) else "",
                "updated": (l.get("write_date") or "")[:10],
            }
            for l in (lignes or [])
        ]

    def chatter(self):
        """Client d'écriture dans le chatter.

        Séparé de la lecture : `odoo_client.py` ne sait que lire, et
        écrire dans le dossier d'un client mérite un chemin explicite.
        """
        from .chatter import OdooChatter

        if not self.configured:
            raise OdooUnavailable("Odoo n'est pas configuré.")
        return OdooChatter(self._url, self._secrets.get())

    def context_pack(self, model: str, record_id: int) -> dict[str, Any]:
        """Pack de contexte prêt pour le prompt, et ce qu'on en tire.

        `client_company` alimente la règle de titre « Client - Sujet » —
        c'est ce qui évite les « Ekonum - … » que tu ne voulais plus.
        """
        try:
            pack = fetch_related_context_pack(self._config(), model, record_id)
        except OdooError as exc:
            raise OdooUnavailable(str(exc)) from exc
        return {
            "summary": pack.get("summary") or "",
            "terms": extract_odoo_glossary_candidates(pack) or list(pack.get("terms") or []),
            "client_company": extract_company_name_from_pack(pack) or "",
        }
