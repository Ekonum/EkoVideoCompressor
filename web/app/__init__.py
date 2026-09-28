"""Serveur de la webapp EkoVideo.

Vit dans le dépôt de l'app macOS pendant toute la phase de parité : les
deux consomment le *même* ``cloud_transcription.py``, et une copie
divergente serait la première chose à casser. Le découplage se fera au
jalon M6, quand l'app macOS sera retirée.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Le moteur partagé (cloud_transcription, odoo_client…) est à la racine
# du dépôt, deux niveaux au-dessus de ce paquet.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
