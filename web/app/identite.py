"""L'identité Google du serveur, sans clé de compte de service.

Google déconseille les clés JSON de compte de service : un fichier que
Google a émis, valable dix ans, qui ouvre la porte depuis n'importe où.
Pour une charge qui tourne hors de Google Cloud, sa recommandation est la
**fédération d'identité de charge de travail** : le serveur prouve qui il
est avec un jeton qu'il signe lui-même, Google l'échange contre un jeton
d'une heure, puis contre celui du compte de service.

Trois partis pris :

**La clé naît sur le serveur et n'en sort pas.** Générée au premier
besoin dans le volume, à côté de la base ; elle ne passe ni par le coffre,
ni par une conversation, ni par un poste. Google n'en connaît que la
moitié publique, déposée dans le fournisseur d'identité du pool.

**Seule, elle n'ouvre rien.** Le pool n'accepte qu'un émetteur et qu'un
sujet précis, et ce sujet n'a qu'un droit : se faire passer pour *un*
compte de service, lui-même membre d'*un* Drive partagé.

**La rotation est un geste d'administration**, pas un déploiement :
supprimer le fichier, relancer ``python -m app.identite``, redéposer le
JWKS dans le fournisseur (voir web/docs/STOCKAGE-VIDEO.md).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

STS_URL = "https://sts.googleapis.com/v1/token"
IAM_URL = "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{compte}:generateAccessToken"
UA = "transcript-identite/1.0"
SUJET = "transcript"


class IdentiteIndisponible(RuntimeError):
    """Google a refusé l'échange, ou la configuration est incomplète."""


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def cle_privee(chemin: Path):
    """La clé RSA du serveur, créée au premier appel.

    Créée en 0600 d'emblée, et non restreinte après coup : entre les deux,
    un autre processus aurait pu la lire.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if not chemin.exists():
        chemin.parent.mkdir(parents=True, exist_ok=True)
        nouvelle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = nouvelle.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descripteur, "wb") as fichier:
            fichier.write(pem)
    return serialization.load_pem_private_key(chemin.read_bytes(), password=None)


def jwk(cle) -> dict[str, str]:
    """La moitié publique, au format JWK, avec l'empreinte RFC 7638 pour
    identifiant : deux clés successives ne se confondent pas."""
    nombres = cle.public_key().public_numbers()

    def entier(n: int) -> str:
        return _b64(n.to_bytes((n.bit_length() + 7) // 8, "big"))

    publique = {"e": entier(nombres.e), "kty": "RSA", "n": entier(nombres.n)}
    empreinte = _b64(hashlib.sha256(
        json.dumps(publique, separators=(",", ":"), sort_keys=True).encode()
    ).digest())
    return {**publique, "alg": "RS256", "use": "sig", "kid": empreinte}


class IdentiteGoogle:
    """Rend un jeton d'accès du compte de service, renouvelé au besoin."""

    def __init__(
        self,
        *,
        chemin_cle: Path,
        fournisseur: str,
        compte: str,
        emetteur: str,
        portee: str,
        opener: Callable[..., Any] | None = None,
        horloge: Callable[[], float] = time.time,
    ) -> None:
        if not (fournisseur and compte and emetteur):
            raise IdentiteIndisponible("Identité Google non configurée.")
        self._chemin = chemin_cle
        # L'audience est le nom complet du fournisseur, précédé de « // » :
        # c'est ainsi que STS reconnaît à quel pool le jeton s'adresse.
        self._audience = "//iam.googleapis.com/" + fournisseur.removeprefix("//iam.googleapis.com/")
        self._compte = compte
        self._emetteur = emetteur.rstrip("/")
        self._portee = portee
        self._ouvrir = opener or (lambda req, timeout=30: urllib.request.urlopen(req, timeout=timeout))
        self._horloge = horloge
        self._jeton = ""
        self._expire = 0.0

    def __call__(self) -> str:
        """Le jeton courant — une minute de marge avant l'expiration, pour
        qu'un morceau d'envoi ne parte pas avec un jeton qui meurt en route."""
        if self._jeton and self._horloge() < self._expire - 60:
            return self._jeton
        federe = self._echanger(self._assertion())
        reponse = self._post(
            IAM_URL.format(compte=urllib.parse.quote(self._compte)),
            json.dumps({"scope": [self._portee], "lifetime": "3600s"}).encode(),
            "application/json",
            jeton=federe,
        )
        self._jeton = reponse["accessToken"]
        self._expire = self._horloge() + 3600
        return self._jeton

    def _assertion(self) -> str:
        import jwt  # PyJWT, déjà présent pour Access

        cle = cle_privee(self._chemin)
        maintenant = int(self._horloge())
        return jwt.encode(
            {
                "iss": self._emetteur,
                "sub": SUJET,
                "aud": self._audience,
                "iat": maintenant,
                "exp": maintenant + 300,
            },
            cle,
            algorithm="RS256",
            headers={"kid": jwk(cle)["kid"]},
        )

    def _echanger(self, assertion: str) -> str:
        reponse = self._post(
            STS_URL,
            urllib.parse.urlencode({
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "audience": self._audience,
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
                "subject_token": assertion,
            }).encode(),
            "application/x-www-form-urlencoded",
        )
        return reponse["access_token"]

    def _post(self, url: str, corps: bytes, type_: str, jeton: str = "") -> dict[str, Any]:
        requete = urllib.request.Request(url, data=corps, method="POST")
        requete.add_header("User-Agent", UA)
        requete.add_header("Content-Type", type_)
        if jeton:
            requete.add_header("Authorization", f"Bearer {jeton}")
        try:
            with self._ouvrir(requete, timeout=30) as reponse:
                return json.loads(reponse.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            # Le corps d'erreur de STS dit *pourquoi* (audience, émetteur,
            # condition) sans rien contenir de secret : il vaut d'être lu.
            try:
                detail = json.loads(exc.read().decode("utf-8") or "{}")
            except ValueError:
                detail = {}
            motif = detail.get("error_description") or (detail.get("error") or {})
            if isinstance(motif, dict):
                motif = motif.get("message", "")
            raise IdentiteIndisponible(
                f"Google a refusé l'identité du serveur ({exc.code}) : {motif}".rstrip(" :")
            ) from exc
        except urllib.error.URLError as exc:
            raise IdentiteIndisponible(f"Google injoignable : {exc.reason}.") from exc


def main() -> None:
    """Affiche le JWKS à déposer dans le fournisseur — en créant la clé si
    elle n'existe pas encore. Rien de secret ne sort."""
    etat = Path(os.environ.get("EKOVIDEO_WEB_STATE", "./state")).resolve()
    chemin = Path(os.environ.get("EKOVIDEO_GCP_CLE", etat / "identite-google.pem"))
    print(json.dumps({"keys": [jwk(cle_privee(chemin))]}))


if __name__ == "__main__":
    main()
