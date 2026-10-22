"""Le tableau de bord de « Mon compte » : combien de réunions, et ce
qu'elles ont coûté, sur une période.

Le regroupement se fait ici plutôt que dans le navigateur : la réponse
reste petite quelle que soit la période, et une réunion tombe dans le
jour de Paris où elle a eu lieu, pas dans celui de l'UTC.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal

from .db import PARIS

Period = Literal["30", "90", "365", "all"]
PERIODS: dict[str, int | None] = {"30": 30, "90": 90, "365": 365, "all": None}

# Au-delà de trois mois, une barre par jour ne se lit plus : 365 barres
# font deux pixels chacune sur un ordinateur, moins d'un sur un téléphone.
DAYS_MAX = 92
WEEKS_MAX = 400


def local_day(moment: str) -> date:
    """Le jour, à Paris. Une date sans fuseau a été écrite par le serveur
    (`datetime.now()`), donc à son heure locale."""
    lu = datetime.fromisoformat(moment.replace("Z", "+00:00"))
    return lu.astimezone(PARIS).date()


def bucket_start(jour: date, bucket: str) -> date:
    if bucket == "week":
        return jour - timedelta(days=jour.weekday())
    if bucket == "month":
        return jour.replace(day=1)
    return jour


def next_bucket(jour: date, bucket: str) -> date:
    if bucket == "week":
        return jour + timedelta(days=7)
    if bucket == "month":
        return (jour.replace(day=28) + timedelta(days=4)).replace(day=1)
    return jour + timedelta(days=1)


def build(
    rows: list[dict[str, Any]],
    period: str,
    usd_per_eur: float | None,
    today: date | None = None,
) -> dict[str, Any]:
    """Les barres de la période, vides comprises : un jour sans réunion
    est une information, pas un trou dans l'axe."""
    today = today or datetime.now(PARIS).date()
    meetings = [(local_day(r["happened_at"]), float(r["cost_usd"] or 0)) for r in rows]
    meetings = [(d, c) for d, c in meetings if d <= today]

    days = PERIODS[period]
    if days is None:
        first = min((d for d, _ in meetings), default=today)
    else:
        first = today - timedelta(days=days - 1)
    span = (today - first).days + 1
    bucket = "day" if span <= DAYS_MAX else "week" if span <= WEEKS_MAX else "month"

    start = bucket_start(first, bucket)
    buckets: dict[date, dict[str, Any]] = {}
    jour = start
    while jour <= today:
        buckets[jour] = {"start": jour.isoformat(), "meetings": 0, "cost_usd": 0.0}
        jour = next_bucket(jour, bucket)
    for d, cost in meetings:
        if d < first:
            continue
        cible = buckets[bucket_start(d, bucket)]
        cible["meetings"] += 1
        cible["cost_usd"] += cost

    def euros(usd: float) -> float | None:
        return round(usd / usd_per_eur, 2) if usd_per_eur else None

    series = list(buckets.values())
    for b in series:
        b["cost_usd"] = round(b["cost_usd"], 4)
        b["cost_eur"] = euros(b["cost_usd"])
    total_usd = round(sum(b["cost_usd"] for b in series), 4)
    return {
        "period": period,
        "bucket": bucket,
        "from": first.isoformat(),
        "to": today.isoformat(),
        "series": series,
        "totals": {
            "meetings": sum(b["meetings"] for b in series),
            "cost_usd": total_usd,
            "cost_eur": euros(total_usd),
        },
    }
