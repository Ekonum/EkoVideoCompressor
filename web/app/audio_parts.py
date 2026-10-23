"""Repères d’écoute du fichier assemblé, relatifs à la partie conservée."""

import json
import math


def audio_parts(context_json: str | None, duration: float) -> list[dict]:
    """Une ancienne réunion ou des métadonnées invalides restent lisibles."""
    try:
        context = json.loads(context_json or "{}")
        parts = context.get("audio_parts", []) if isinstance(context, dict) else []
        if not isinstance(parts, list) or len(parts) > 200:
            return []
        result, previous = [], 0.0
        for part in parts:
            if not isinstance(part, dict):
                return []
            name, start, end = part.get("name"), part.get("start"), part.get("end")
            if (not isinstance(name, str) or not name or len(name) > 500
                or any(isinstance(n, bool) or not isinstance(n, (int, float))
                       or not math.isfinite(n) for n in (start, end))
                or start < previous or end <= start or end > duration + 0.1):
                return []
            result.append({"name": name, "start": start, "end": end})
            previous = end
        return result
    except (TypeError, ValueError):
        return []
