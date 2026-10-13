"""Combien de temps prend une fenêtre, et où en est-elle.

Le serveur ne sait pas où en est Gemini sur une fenêtre : il sait quand
elle a commencé, et combien de temps ont pris les précédentes. La barre
avance donc sur une estimation, plafonnée tant que la fenêtre n'est pas
réellement transcrite — elle ne doit jamais annoncer fini ce qui ne
l'est pas.
"""

from __future__ import annotations

import math
from datetime import datetime

# Mesuré sur 139 réunions retraitées le 13/10/2026 : environ 10 s fixes
# par appel, puis 0,08 s par seconde d'audio. Sert tant que l'historique
# horodaté ne suffit pas.
OVERHEAD_SECONDS = 10.0
DEFAULT_RATIO = 0.08
# En dessous, l'historique est trop maigre pour remplacer la mesure.
MIN_SAMPLES = 5
# Ce qu'une fenêtre peut afficher à l'heure prévue ; au-delà, elle
# s'approche de la fin sans jamais l'atteindre.
AT_ESTIMATE = 0.9
CEILING = 0.99


def estimated_seconds(audio_seconds: float, ratio: float) -> float:
    return OVERHEAD_SECONDS + ratio * max(0.0, audio_seconds)


def ratio_from_history(samples: list[tuple[float, float]]) -> float:
    """Médiane des secondes de calcul par seconde d'audio.

    ``samples`` : (secondes d'audio, secondes de transcription). La
    médiane plutôt que la moyenne : une fenêtre qui a attendu une
    relance de Gemini ne doit pas ralentir toutes les barres."""
    ratios = sorted(
        max(0.0, duree - OVERHEAD_SECONDS) / audio
        for audio, duree in samples
        if audio > 0 and duree >= 0
    )
    if len(ratios) < MIN_SAMPLES:
        return DEFAULT_RATIO
    milieu = len(ratios) // 2
    if len(ratios) % 2:
        return ratios[milieu]
    return (ratios[milieu - 1] + ratios[milieu]) / 2


def capped(share: float) -> float:
    """Part affichée d'une fenêtre, pour une part de temps écoulé.

    Linéaire jusqu'à l'heure prévue (90 %), puis asymptotique : une
    fenêtre en retard avance encore un peu, sans jamais toucher 100 %.
    Le pendant côté écran est dans ``client/src/progression.js``."""
    if share <= 0:
        return 0.0
    if share <= 1:
        return AT_ESTIMATE * share
    return AT_ESTIMATE + (CEILING - AT_ESTIMATE) * (1 - math.exp(-(share - 1)))


def elapsed_seconds(started_at: str | None, now: datetime) -> float | None:
    if not started_at:
        return None
    try:
        debut = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    return max(0.0, (now - debut).total_seconds())


def chunk_fraction(chunk: dict, ratio: float, now: datetime) -> float:
    if chunk["status"] == "termine":
        return 1.0
    if chunk["status"] != "en_cours":
        return 0.0
    ecoule = elapsed_seconds(chunk.get("started_at"), now)
    if ecoule is None:
        # Envoyée, mais elle attend son tour derrière les autres.
        return 0.0
    audio = float(chunk["end_second"]) - float(chunk["start_second"])
    return capped(ecoule / estimated_seconds(audio, ratio))


def transcription_fraction(chunks: list[dict], ratio: float, now: datetime) -> float:
    """Part de la transcription faite, pondérée par la durée d'audio."""
    total = sum(float(c["end_second"]) - float(c["start_second"]) for c in chunks)
    if total <= 0:
        return 0.0
    return sum(
        chunk_fraction(c, ratio, now) * (float(c["end_second"]) - float(c["start_second"]))
        for c in chunks
    ) / total
