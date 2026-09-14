"""Configuration, lue une fois depuis l'environnement.

Aucun secret en dur : la clé Gemini vient du broker (voir
:mod:`app.secrets`), et l'identité de l'utilisateur du jeton Cloudflare
Access. Ce module ne connaît que des adresses et des plafonds.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path
    chunk_dir: Path

    # Cloudflare Access
    access_team_domain: str
    access_aud: str

    # Broker de secrets Ekonum
    broker_url: str
    broker_token: str
    broker_item: str
    broker_field: str

    # Garde-fou budget : plafond d'équipe, la clé Gemini étant partagée.
    monthly_budget_usd: float

    # Bac à sable local : court-circuite Access et le broker. Refusé dès
    # qu'une configuration Access est présente, pour qu'un déploiement ne
    # puisse pas démarrer ouvert par accident.
    dev_mode: bool
    dev_user_email: str
    dev_api_key: str

    @classmethod
    def from_env(cls) -> "Settings":
        state = Path(os.environ.get("EKOVIDEO_WEB_STATE", "./state")).resolve()
        team = os.environ.get("EKOVIDEO_ACCESS_TEAM_DOMAIN", "").strip()
        dev = _flag("EKOVIDEO_WEB_DEV_MODE")
        if dev and team:
            raise RuntimeError(
                "EKOVIDEO_WEB_DEV_MODE est actif alors qu'un domaine "
                "Cloudflare Access est configuré : refus de démarrer sans "
                "authentification."
            )
        return cls(
            db_path=Path(os.environ.get("EKOVIDEO_WEB_DB", state / "ekovideo.db")),
            chunk_dir=Path(os.environ.get("EKOVIDEO_WEB_CHUNKS", state / "chunks")),
            access_team_domain=team,
            access_aud=os.environ.get("EKOVIDEO_ACCESS_AUD", "").strip(),
            broker_url=os.environ.get(
                "EKONUM_BROKER_URL", "http://ekonum-secret-broker:8710/v1/secret"
            ).strip(),
            broker_token=os.environ.get("EKONUM_TOKEN", "").strip(),
            broker_item=os.environ.get(
                # Le nom exact dans le coffre — vérifié avec « ekonum-secret
                # list ». « Ekonum - API Gemini » n'existe pas, et le broker
                # aurait répondu sans valeur exploitable.
                "EKONUM_BROKER_ITEM", "Ekonum - API Google Gemini"
            ),
            broker_field=os.environ.get("EKONUM_BROKER_FIELD", "Clé API"),
            monthly_budget_usd=float(os.environ.get("EKOVIDEO_MONTHLY_BUDGET_USD", "50")),
            dev_mode=dev,
            dev_user_email=os.environ.get("EKOVIDEO_DEV_USER", "dev@ekonum.fr").strip(),
            dev_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        )
