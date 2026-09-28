"""Stockage des vidéos compressées, hors du serveur.

Le serveur n'a ni la place ni la vocation de garder des vidéos : 47 Go
libres sur le VPS, 95 Mo par heure de réunion. Elles vont dans un **Drive
partagé dédié**, dont le seul membre est un compte de service. Personne ne
le voit dans son Drive ; transcript est la seule porte d'entrée.

Deux partis pris :

**Le serveur relaie, il ne garde rien.** L'envoi arrive par morceaux de
16 Mio et repart aussitôt vers Drive par une session d'envoi reprenable ;
la lecture est un flux, plage par plage. Aucun fichier ne touche le disque,
et la mémoire ne voit jamais plus d'un morceau.

**Une interface étroite**, parce que ce stockage est provisoire : GCS le
remplacera (voir docs/BACKLOG.md), et Odoo saura alors lire les mêmes
fichiers. Ouvrir un envoi, envoyer un morceau, lire une plage, supprimer —
rien d'autre ne doit dépendre de Drive.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterator

log = logging.getLogger("ekovideo.web")

UA = "transcript-stockage/1.0"
PORTEE = "https://www.googleapis.com/auth/drive"
ENVOI_URL = "https://www.googleapis.com/upload/drive/v3/files"
FICHIERS_URL = "https://www.googleapis.com/drive/v3/files"

# Drive exige des morceaux multiples de 256 Kio (sauf le dernier). 16 Mio
# passe sous la limite de corps de Cloudflare et reste modeste pour un
# conteneur à 256 Mo.
MORCEAU = 16 * 1024 * 1024


class StockageIndisponible(RuntimeError):
    """Le stockage vidéo n'est pas configuré ou ne répond pas."""


@dataclass(slots=True)
class Plage:
    """Une réponse de lecture : statut, en-têtes à relayer, et le flux."""

    statut: int
    entetes: dict[str, str]
    flux: Iterator[bytes]


class DriveStockage:
    """Drive partagé, piloté par un compte de service."""

    def __init__(
        self,
        jeton: Callable[[], str],
        dossier_id: str,
        *,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        """``jeton`` rend un jeton d'accès Drive valide : c'est
        ``identite.IdentiteGoogle``, qui le renouvelle seul. Le stockage
        n'a pas à savoir comment le serveur prouve qui il est."""
        if jeton is None or not dossier_id:
            raise StockageIndisponible("Stockage vidéo non configuré.")
        self._jeton_acces = jeton
        self._dossier = dossier_id
        self._ouvrir = opener or (lambda req, timeout=120: urllib.request.urlopen(req, timeout=timeout))

    # -- plomberie HTTP ----------------------------------------------------

    def _requete(
        self,
        methode: str,
        url: str,
        *,
        corps: bytes | None = None,
        type_: str = "",
        entetes: dict[str, str] | None = None,
        auth: bool = True,
    ) -> Any:
        requete = urllib.request.Request(url, data=corps, method=methode)
        requete.add_header("User-Agent", UA)
        if type_:
            requete.add_header("Content-Type", type_)
        if auth:
            try:
                jeton = self._jeton_acces()
            except RuntimeError as exc:
                # Un refus d'identité (pool, condition, JWKS périmé) est,
                # pour qui envoie ou lit une vidéo, un stockage indisponible
                # — avec le motif de Google, pour qu'on sache quoi réparer.
                raise StockageIndisponible(str(exc)) from exc
            requete.add_header("Authorization", f"Bearer {jeton}")
        for cle, valeur in (entetes or {}).items():
            requete.add_header(cle, valeur)
        try:
            return self._ouvrir(requete, timeout=120)
        except urllib.error.HTTPError as exc:
            # 308 n'est pas une erreur : c'est « morceau reçu, continue ».
            if exc.code == 308:
                return exc
            raise StockageIndisponible(
                f"Google Drive a refusé {methode} ({exc.code})."
            ) from exc
        except urllib.error.URLError as exc:
            raise StockageIndisponible(f"Google Drive injoignable : {exc.reason}.") from exc

    # -- l'interface ---------------------------------------------------------

    def ouvrir_envoi(self, nom: str, taille: int, type_: str = "video/mp4") -> str:
        """Ouvre une session d'envoi reprenable ; rend son adresse.

        L'adresse vaut autorisation d'écrire *ce* fichier : elle reste
        côté serveur, le navigateur ne la voit jamais.
        """
        metadonnees = json.dumps({"name": nom, "parents": [self._dossier]}).encode()
        reponse = self._requete(
            "POST",
            f"{ENVOI_URL}?uploadType=resumable&supportsAllDrives=true",
            corps=metadonnees,
            type_="application/json; charset=UTF-8",
            entetes={
                "X-Upload-Content-Type": type_,
                "X-Upload-Content-Length": str(int(taille)),
            },
        )
        with reponse:
            session = reponse.headers.get("Location", "")
        if not session:
            raise StockageIndisponible("Drive n'a pas ouvert de session d'envoi.")
        return session

    def envoyer_morceau(
        self, session: str, debut: int, octets: bytes, total: int
    ) -> str | None:
        """Relaie un morceau. Rend l'identifiant du fichier une fois le
        dernier morceau reçu, ``None`` tant qu'il en manque."""
        fin = debut + len(octets) - 1
        reponse = self._requete(
            "PUT",
            session,
            corps=octets,
            entetes={"Content-Range": f"bytes {debut}-{fin}/{int(total)}"},
            auth=False,  # la session porte déjà l'autorisation
        )
        with reponse:
            if getattr(reponse, "code", getattr(reponse, "status", 200)) == 308:
                return None
            fichier = json.loads(reponse.read().decode("utf-8") or "{}")
        return str(fichier.get("id") or "") or None

    def lire(self, fichier_id: str, plage: str = "") -> Plage:
        """Flux d'une plage du fichier — le lecteur vidéo demande des
        plages pour se déplacer dans la réunion sans tout télécharger."""
        reponse = self._requete(
            "GET",
            f"{FICHIERS_URL}/{urllib.parse.quote(fichier_id)}?alt=media&supportsAllDrives=true",
            entetes={"Range": plage} if plage else None,
        )
        statut = getattr(reponse, "status", 200)
        entetes = {
            cle: reponse.headers[cle]
            for cle in ("Content-Type", "Content-Length", "Content-Range")
            if reponse.headers.get(cle)
        }
        entetes["Accept-Ranges"] = "bytes"

        def flux() -> Iterator[bytes]:
            with reponse:
                while True:
                    bloc = reponse.read(1024 * 1024)
                    if not bloc:
                        return
                    yield bloc

        return Plage(statut=statut, entetes=entetes, flux=flux())

    def supprimer(self, fichier_id: str) -> None:
        """Suppression définitive — le Drive partagé n'a pas de corbeille
        à vider après coup : c'est la corbeille de transcript qui en tient
        lieu."""
        try:
            self._requete(
                "DELETE",
                f"{FICHIERS_URL}/{urllib.parse.quote(fichier_id)}?supportsAllDrives=true",
            ).close()
        except StockageIndisponible as exc:
            # Un fichier déjà absent ne doit pas empêcher de purger la
            # réunion ; le reste se journalise pour qu'on le voie.
            if "(404)" not in str(exc):
                raise
