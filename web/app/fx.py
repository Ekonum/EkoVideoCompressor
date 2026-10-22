"""Le cours euro-dollar, relevé une fois par mois auprès de la BCE.

Gemini se paie en dollars ; le tableau de bord montre des euros. C'est un
ordre de grandeur, pas une comptabilité : le cours de référence du premier
jour où on le demande vaut pour tout le mois. La BCE le publie sans clé ni
compte, chaque jour ouvré vers 16 h.
"""
from __future__ import annotations

import logging
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Callable

from .db import PARIS, Database

ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
# Une BCE injoignable ne doit pas coûter un appel à chaque affichage du
# tableau de bord : on retente une heure plus tard, avec le dernier cours
# connu en attendant.
RETRY_SECONDS = 3600

log = logging.getLogger("ekovideo.web")


def parse_ecb(xml: bytes) -> tuple[float, str]:
    """Le cours du dollar (USD pour 1 EUR) et le jour de sa publication."""
    racine = ET.fromstring(xml)
    for cube in racine.iter():
        if cube.tag.endswith("Cube") and cube.get("time"):
            jour = cube.get("time")
            for taux in cube:
                if taux.get("currency") == "USD":
                    return float(taux.get("rate")), jour
    raise ValueError("Pas de cours du dollar dans la réponse de la BCE.")


class EuroRate:
    def __init__(
        self,
        db: Database,
        *,
        opener: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db = db
        self._open = opener or (lambda url, timeout: urllib.request.urlopen(url, timeout=timeout))
        self._clock = clock
        self._failed_at: float | None = None

    def current(self) -> dict[str, Any] | None:
        """Le cours du mois, ou à défaut le dernier connu, ou rien."""
        month = datetime.now(PARIS).strftime("%Y-%m")
        known = self._db.fx_rate(month)
        if known:
            return known
        if self._failed_at is not None and self._clock() - self._failed_at < RETRY_SECONDS:
            return self._db.fx_rate()
        try:
            with self._open(ECB_DAILY, timeout=5) as reponse:
                usd_per_eur, published = parse_ecb(reponse.read())
        except (urllib.error.URLError, OSError, ET.ParseError, ValueError) as exc:
            log.warning("Cours de la BCE indisponible : %s", exc)
            self._failed_at = self._clock()
            return self._db.fx_rate()
        self._failed_at = None
        self._db.set_fx_rate(month, usd_per_eur, published)
        return self._db.fx_rate(month)
