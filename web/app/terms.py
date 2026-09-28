"""Correction d'un terme mal entendu, partout à la fois.

Reprend la sémantique de ``library_replace_term`` (moteur macOS) : mot
entier, insensible à la casse, normalisé NFC. La normalisation n'est pas
un détail — « Acritec » tapé au clavier et « Acritec » sorti du modèle
peuvent différer par la composition des accents, et la recherche
échouerait silencieusement.

Écart assumé : le serveur n'a pas d'artefacts sur disque, la
transcription étant une colonne. Il n'y a donc que deux endroits à
corriger au lieu de quatre.
"""

from __future__ import annotations

import re
import unicodedata


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", str(value or "").strip())


def replace_term(
    *,
    transcript: str,
    segments: list[dict],
    technical_terms: list[str],
    old: str,
    new: str,
) -> tuple[str, list[dict], list[str], int]:
    """Renvoie (transcription, segments, termes, occurrences).

    Sans effet quand l'un des deux termes est vide ou qu'ils ne diffèrent
    que par la casse — remplacer « odoo » par « Odoo » dans un texte déjà
    correct n'apporterait rien et brouillerait le compteur.
    """
    old_n, new_n = _nfc(old), _nfc(new)
    if not old_n or not new_n or old_n.lower() == new_n.lower():
        return transcript, segments, technical_terms, 0

    pattern = re.compile(r"\b" + re.escape(old_n) + r"\b", re.IGNORECASE)
    occurrences = 0

    new_transcript, count = pattern.subn(new_n, _nfc(transcript))
    occurrences += count

    new_segments: list[dict] = []
    for segment in segments:
        updated = dict(segment)
        text, count = pattern.subn(new_n, _nfc(updated.get("text") or ""))
        updated["text"] = text
        occurrences += count
        new_segments.append(updated)

    # Le glossaire lui-même porte la coquille : la corriger ici évite
    # qu'elle ne soit resoufflée au modèle à la prochaine transcription.
    seen: set[str] = set()
    new_terms: list[str] = []
    for term in technical_terms:
        replaced = pattern.sub(new_n, _nfc(term))
        key = replaced.lower()
        if replaced and key not in seen:
            seen.add(key)
            new_terms.append(replaced)

    return new_transcript, new_segments, new_terms, occurrences
