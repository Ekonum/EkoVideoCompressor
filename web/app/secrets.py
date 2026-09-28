"""Lecture de la clé Gemini via ekonum-secret-broker.

Le broker est en lecture seule et contingenté (30/min, 200/h, ~12
secrets distincts par 15 min) : on lit **une fois** au démarrage et on
garde en cache, avec une relecture uniquement si la clé se fait refuser.

Deux pièges du broker, appris à ses dépens ailleurs : il faut un
``User-Agent`` réel (Cloudflare renvoie sinon un 1010), et le conteneur
doit avoir rejoint le réseau Docker externe ``ekonum-broker``.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

USER_AGENT = "EkoVideoWeb/1.0 (+https://ekonum.fr)"


class SecretError(RuntimeError):
    """La clé n'a pas pu être obtenue — message destiné à l'utilisateur."""


class GeminiKey:
    """Clé partagée d'équipe, mémorisée jusqu'à invalidation explicite."""

    def __init__(
        self,
        *,
        url: str,
        token: str,
        item: str,
        field: str,
        static_key: str = "",
        opener=None,
    ) -> None:
        self._url = url
        self._token = token
        self._item = item
        self._field = field
        self._static = (static_key or "").strip()
        self._opener = opener or urllib.request.urlopen
        self._cached = ""
        self._lock = threading.Lock()

    def get(self) -> str:
        if self._static:
            return self._static
        with self._lock:
            if not self._cached:
                self._cached = self._fetch()
            return self._cached

    def invalidate(self) -> None:
        """À appeler sur un 401 : la prochaine lecture repassera au broker."""
        with self._lock:
            self._cached = ""

    def _fetch(self) -> str:
        if not self._token:
            raise SecretError(
                "Aucun jeton broker configuré (EKONUM_TOKEN) : impossible de "
                "récupérer la clé Gemini."
            )
        body = json.dumps({"item": self._item, "field": self._field}).encode("utf-8")
        request = urllib.request.Request(
            self._url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with self._opener(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            raise SecretError(
                f"Le broker de secrets a refusé la demande ({exc.code}). "
                "Vérifiez EKONUM_TOKEN et le nom de l'élément."
            ) from exc
        except urllib.error.URLError as exc:
            raise SecretError(
                f"Broker de secrets injoignable : {exc.reason}. Le conteneur "
                "est-il bien sur le réseau Docker « ekonum-broker » ?"
            ) from exc

        key = str(payload.get("value") or payload.get("secret") or "").strip()
        if not key:
            raise SecretError(
                "Le broker a répondu sans valeur exploitable pour "
                f"« {self._item} / {self._field} »."
            )
        return key
