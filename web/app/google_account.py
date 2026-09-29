"""Le compte Google de chacun : connexion OAuth, et son Drive.

Sert à retrouver les enregistrements d'avant transcript, rangés un peu
partout dans le Drive. Chacun connecte **son** compte, comme il donne sa
clé Odoo : transcript ne voit que ce que la personne voit, et ne déplace
un fichier qu'en son nom.

L'application OAuth est « interne » au Workspace Ekonum : un compte hors
de l'organisation ne peut pas la voir. Le jeton de rafraîchissement est
chiffré en base ; le jeton d'accès, lui, ne vit qu'en mémoire.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

log = logging.getLogger("ekovideo.web")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVES_URL = "https://www.googleapis.com/drive/v3/drives"
UA = "transcript-google/1.0"

# `drive` entier, pas `drive.readonly` : retirer l'original une fois copié
# exige d'écrire. L'application étant interne, ce périmètre n'appelle pas
# de vérification par Google.
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/drive"]

MEDIA_FIELDS = (
    "id,name,mimeType,size,md5Checksum,createdTime,modifiedTime,driveId,"
    "owners(emailAddress,me),webViewLink,videoMediaMetadata(durationMillis)"
)


class GoogleUnavailable(RuntimeError):
    """Google a refusé, ou la connexion n'est pas configurée."""


def pkce_pair() -> tuple[str, str]:
    """Un vérificateur PKCE et son défi S256."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def email_from_id_token(id_token: str) -> str:
    """L'adresse du jeton d'identité.

    Pas de vérification de signature ici, et c'est voulu : le jeton vient
    est reçu directement du point de terminaison de Google, par TLS, en
    échange du code — c'est le cas où OpenID Connect l'autorise.
    """
    try:
        charge = id_token.split(".")[1]
        charge += "=" * (-len(charge) % 4)
        return str(json.loads(base64.urlsafe_b64decode(charge)).get("email") or "").lower()
    except (IndexError, ValueError):
        return ""


class _Http:
    def __init__(self, opener: Callable[..., Any] | None = None) -> None:
        self._ouvrir = opener or (lambda req, timeout=60: urllib.request.urlopen(req, timeout=timeout))

    def call(
        self, method: str, url: str, *, token: str = "", form: dict | None = None,
        body: dict | None = None,
    ) -> dict[str, Any]:
        data = None
        requete = urllib.request.Request(url, method=method)
        requete.add_header("User-Agent", UA)
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            requete.add_header("Content-Type", "application/x-www-form-urlencoded")
        elif body is not None:
            data = json.dumps(body).encode()
            requete.add_header("Content-Type", "application/json")
        if token:
            requete.add_header("Authorization", f"Bearer {token}")
        requete.data = data
        try:
            with self._ouvrir(requete, timeout=60) as reponse:
                texte = reponse.read().decode("utf-8")
                return json.loads(texte) if texte.strip() else {}
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8") or "{}")
            except ValueError:
                detail = {}
            motif = detail.get("error_description") or detail.get("error") or ""
            if isinstance(motif, dict):
                motif = motif.get("message", "")
            raise GoogleUnavailable(f"Google a refusé ({exc.code}) : {motif}".rstrip(" :")) from exc
        except urllib.error.URLError as exc:
            raise GoogleUnavailable(f"Google injoignable : {exc.reason}.") from exc


class GoogleOAuth:
    """Le client OAuth de transcript."""

    def __init__(
        self, *, client_id: str, client_secret: Callable[[], str], redirect_uri: str,
        domain: str = "", opener: Callable[..., Any] | None = None,
    ) -> None:
        self.client_id = client_id
        self._secret = client_secret
        self.redirect_uri = redirect_uri
        self.domain = domain
        self._http = _Http(opener)

    @property
    def configured(self) -> bool:
        return bool(self.client_id)

    def authorization_url(self, state: str, challenge: str, login_hint: str = "") -> str:
        parametres = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Hors ligne, et le consentement redemandé : sans cela, Google
            # ne rend le jeton de rafraîchissement qu'à la toute première
            # connexion, et une reconnexion resterait sans lendemain.
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        if login_hint:
            parametres["login_hint"] = login_hint
        if self.domain:
            parametres["hd"] = self.domain
        return f"{AUTH_URL}?{urllib.parse.urlencode(parametres)}"

    def exchange(self, code: str, verifier: str) -> dict[str, Any]:
        return self._http.call("POST", TOKEN_URL, form={
            "code": code,
            "client_id": self.client_id,
            "client_secret": self._secret(),
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        })

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        return self._http.call("POST", TOKEN_URL, form={
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self._secret(),
            "grant_type": "refresh_token",
        })

    def revoke(self, token: str) -> None:
        try:
            self._http.call("POST", REVOKE_URL, form={"token": token})
        except GoogleUnavailable as exc:
            # Déjà révoqué côté Google : l'oublier ici suffit.
            log.info("révocation Google : %s", exc)


class AccessTokens:
    """Jetons d'accès en mémoire, par personne, renouvelés une minute avant
    leur fin."""

    def __init__(self, oauth: GoogleOAuth, refresh_token_for: Callable[[int], str],
                 clock: Callable[[], float] = time.time) -> None:
        self._oauth = oauth
        self._refresh_token_for = refresh_token_for
        self._clock = clock
        self._cache: dict[int, tuple[str, float]] = {}

    def for_user(self, user_id: int) -> str:
        jeton, fin = self._cache.get(user_id, ("", 0.0))
        if jeton and self._clock() < fin - 60:
            return jeton
        rafraichissement = self._refresh_token_for(user_id)
        if not rafraichissement:
            raise GoogleUnavailable("Google Drive n'est pas connecté.")
        reponse = self._oauth.refresh(rafraichissement)
        jeton = str(reponse.get("access_token") or "")
        self._cache[user_id] = (jeton, self._clock() + float(reponse.get("expires_in") or 3600))
        return jeton

    def forget(self, user_id: int) -> None:
        self._cache.pop(user_id, None)


class UserDrive:
    """Le Drive d'une personne, avec son jeton — jamais celui d'un autre."""

    def __init__(self, token: Callable[[], str], opener: Callable[..., Any] | None = None) -> None:
        self._token = token
        self._http = _Http(opener)

    def _get(self, url: str) -> dict[str, Any]:
        return self._http.call("GET", url, token=self._token())

    def shared_drives(self) -> dict[str, str]:
        noms: dict[str, str] = {}
        jeton = ""
        while True:
            page = self._get(f"{DRIVES_URL}?" + urllib.parse.urlencode({
                "pageSize": "100", "fields": "nextPageToken,drives(id,name)",
                **({"pageToken": jeton} if jeton else {}),
            }))
            noms.update({d["id"]: d["name"] for d in page.get("drives", [])})
            jeton = page.get("nextPageToken", "")
            if not jeton:
                return noms

    def media_files(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Tous les fichiers audio et vidéo que la personne voit : son Drive,
        les Drive partagés dont elle est membre, ce qu'on lui a partagé."""
        requete = (
            "trashed = false and (mimeType contains 'video/' or mimeType contains 'audio/')"
        )
        fichiers: list[dict[str, Any]] = []
        jeton = ""
        while len(fichiers) < limit:
            page = self._get(f"{FILES_URL}?" + urllib.parse.urlencode({
                "q": requete,
                "corpora": "allDrives",
                "includeItemsFromAllDrives": "true",
                "supportsAllDrives": "true",
                "pageSize": "1000",
                "fields": f"nextPageToken,files({MEDIA_FIELDS})",
                **({"pageToken": jeton} if jeton else {}),
            }))
            fichiers.extend(page.get("files", []))
            jeton = page.get("nextPageToken", "")
            if not jeton:
                break
        return fichiers[:limit]

    def file(self, file_id: str) -> dict[str, Any]:
        return self._get(f"{FILES_URL}/{urllib.parse.quote(file_id)}?" + urllib.parse.urlencode({
            "supportsAllDrives": "true", "fields": MEDIA_FIELDS,
        }))

    def grant_reader(self, file_id: str, email: str) -> str:
        """Laisse `email` lire le fichier, le temps que le compte de service
        de transcript en fasse une copie. Rend l'identifiant du droit, pour
        le retirer ensuite."""
        reponse = self._http.call(
            "POST",
            f"{FILES_URL}/{urllib.parse.quote(file_id)}/permissions?"
            + urllib.parse.urlencode({"supportsAllDrives": "true", "sendNotificationEmail": "false"}),
            token=self._token(),
            body={"type": "user", "role": "reader", "emailAddress": email},
        )
        return str(reponse.get("id") or "")

    def revoke_permission(self, file_id: str, permission_id: str) -> None:
        self._http.call(
            "DELETE",
            f"{FILES_URL}/{urllib.parse.quote(file_id)}/permissions/{urllib.parse.quote(permission_id)}"
            "?supportsAllDrives=true",
            token=self._token(),
        )

    def trash(self, file_id: str) -> None:
        """À la corbeille du Drive, pas au néant : trente jours pour se
        raviser."""
        self._http.call(
            "PATCH",
            f"{FILES_URL}/{urllib.parse.quote(file_id)}?supportsAllDrives=true",
            token=self._token(),
            body={"trashed": True},
        )
