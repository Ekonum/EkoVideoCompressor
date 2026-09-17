"""Chiffrement des secrets confiés par les utilisateurs.

Une clé API Odoo personnelle donne accès à Odoo **au nom de son
propriétaire**. La garder en clair dans la base reviendrait à ce qu'une
copie du volume compromette tous les comptes d'un coup.

Le choix qui compte ici est le **refus de dégrader** : sans clé de
chiffrement configurée, on n'accepte pas le secret. Stocker en clair
« en attendant » est le genre de provisoire qui reste.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CoffreIndisponible(RuntimeError):
    """Aucune clé de chiffrement : on refuse de stocker un secret."""


class Coffre:
    def __init__(self, cle: str) -> None:
        self._fernet = Fernet(cle.encode("utf-8")) if cle else None

    @property
    def disponible(self) -> bool:
        return self._fernet is not None

    def chiffrer(self, valeur: str) -> str:
        if self._fernet is None:
            raise CoffreIndisponible(
                "Aucune clé de chiffrement configurée (EKOVIDEO_SECRET_KEY) : "
                "le serveur refuse d'enregistrer une clé API en clair."
            )
        return self._fernet.encrypt(valeur.encode("utf-8")).decode("ascii")

    def dechiffrer(self, jeton: str) -> str:
        if self._fernet is None or not jeton:
            return ""
        try:
            return self._fernet.decrypt(jeton.encode("ascii")).decode("utf-8")
        except InvalidToken:
            # La clé de chiffrement a changé : le secret est illisible,
            # et le dire vaut mieux que de partir avec une valeur vide
            # qu'Odoo refuserait sans qu'on sache pourquoi.
            raise CoffreIndisponible(
                "Le secret enregistré est illisible avec la clé de chiffrement "
                "actuelle. Enregistre à nouveau ta clé API Odoo."
            ) from None

    @staticmethod
    def nouvelle_cle() -> str:
        return Fernet.generate_key().decode("ascii")
