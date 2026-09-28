#!/usr/bin/env python3
"""Fabrique un jeton d'API depuis le conteneur.

Amorçage : créer un jeton par l'API demande une session humaine, et une
session humaine demande un navigateur. Cette porte-là contourne le
problème sans l'affaiblir — elle exige un accès *shell au conteneur*,
c'est-à-dire déjà plus de pouvoir qu'un jeton n'en donnera jamais.

    docker exec transcript python web/bin/mint_token.py robin@ekonum.fr "script de test"

Le jeton s'affiche **une seule fois** : la base n'en garde que
l'empreinte, et rien ne permet de le retrouver ensuite.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Database  # noqa: E402
from app.settings import Settings  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1
    email = sys.argv[1]
    nom = sys.argv[2] if len(sys.argv) > 2 else "jeton d'API"

    db = Database(Settings.from_env().db_path)
    owner = db.user_id_for_email(email)
    _, secret = db.create_api_token(owner, nom)

    print(f"Compte : {email}")
    print(f"Nom    : {nom}")
    print(f"Jeton  : {secret}")
    print("\nIl ne sera plus jamais affiché.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
