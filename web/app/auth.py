"""Authentification Cloudflare Access.

Le piège classique : se contenter de l'en-tête
``Cf-Access-Authenticated-User-Email``. N'importe qui atteignant le
conteneur directement peut la forger. On vérifie donc le **jeton**
(``Cf-Access-Jwt-Assertion``) contre les clés publiques de l'équipe, en
contrôlant l'audience — c'est le modèle retenu par sync-hub.
"""

from __future__ import annotations

import threading

import jwt
from jwt import PyJWKClient

_CERTS_PATH = "/cdn-cgi/access/certs"


class AuthError(RuntimeError):
    """Jeton absent, expiré ou destiné à une autre application."""


class AccessVerifier:
    """Vérifie les jetons Access, avec les clés publiques en cache."""

    def __init__(self, team_domain: str, audience: str, *, jwk_client=None) -> None:
        self.team_domain = (team_domain or "").strip().rstrip("/")
        self.audience = (audience or "").strip()
        self._jwk_client = jwk_client
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.team_domain and self.audience)

    def _client(self) -> PyJWKClient:
        with self._lock:
            if self._jwk_client is None:
                domain = self.team_domain
                if not domain.startswith("http"):
                    domain = f"https://{domain}"
                # PyJWKClient garde les clés en cache : un redémarrage de
                # Cloudflare ne déclenche pas une tempête de requêtes.
                self._jwk_client = PyJWKClient(f"{domain}{_CERTS_PATH}")
            return self._jwk_client

    def email_from_token(self, token: str) -> str:
        raw = (token or "").strip()
        if not raw:
            raise AuthError("Jeton Cloudflare Access absent.")
        try:
            key = self._client().get_signing_key_from_jwt(raw)
            claims = jwt.decode(
                raw,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
            )
        except Exception as exc:  # jwt lève une famille entière d'erreurs
            raise AuthError(f"Jeton Cloudflare Access invalide : {exc}") from exc

        email = str(claims.get("email") or "").strip().lower()
        if not email:
            raise AuthError("Le jeton Access ne porte pas d'adresse e-mail.")
        return email
