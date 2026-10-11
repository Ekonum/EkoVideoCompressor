"""Récupérer l'historique : les enregistrements d'avant transcript.

Avant transcript, les réunions finissaient un peu partout : vidéo
compressée dans le Drive, transcription collée dans Odoo, fichier resté
sur le Mac. Ce module en fait l'inventaire et les range dans transcript,
à la date de l'enregistrement.

Trois règles :

**Un inventaire, jamais une aspiration.** Le Drive mêle réunions,
tutoriels et voix off : on propose, la personne coche. Rien n'est copié ni
retiré sans son geste.

**Jamais deux fois la même chose.** Chaque fichier récupéré est retenu par
sa provenance et son empreinte, pour toute l'équipe : un fichier du Drive
partagé récupéré par l'un apparaît « déjà récupéré » chez l'autre, et deux
copies du même fichier n'en font qu'une.

**L'original ne part qu'après une copie vérifiée**, et vers la corbeille
du Drive : trente jours pour se raviser. La copie, elle, se fait chez
Google — pas un octet ne passe par le serveur ni par le poste.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import PurePosixPath
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from .coffre import Coffre, CoffreIndisponible
from .google_account import (
    AccessTokens,
    GoogleOAuth,
    GoogleUnavailable,
    UserDrive,
    email_from_id_token,
    pkce_pair,
)
from .notes import SAME_MEETING, author_name, best_match, fingerprint, overlap, read_note, words
from .odoo import OdooGateway, OdooUnavailable
from .stockage import MORCEAU, StockageIndisponible
from .transcription import transcript_text

log = logging.getLogger("ekovideo.web")

PARIS = ZoneInfo("Europe/Paris")

# Ce qui, dans un nom de fichier, désigne presque sûrement autre chose
# qu'une réunion. La liste reste courte : dans le doute, on propose, et la
# personne tranche.
NOT_MEETING = re.compile(
    r"tuto|narration|voix[ -_]?off|sans[ -_]voix|musique|jingle|teaser|g[ée]n[ée]rique|"
    r"screencast|intro\b|outro\b",
    re.IGNORECASE,
)
MEETING_HINTS = re.compile(
    r"r[ée]union|meeting|call|visio|meet|rdv|d[ée]mo|recording|enregistrement|[ée]change|point\b",
    re.IGNORECASE,
)
MONTHS = {
    "janv": 1, "jan": 1, "févr": 2, "fevr": 2, "fév": 2, "fev": 2, "mars": 3, "avr": 4,
    "mai": 5, "juin": 6, "juil": 7, "août": 8, "aout": 8, "sept": 9, "oct": 10,
    "nov": 11, "déc": 12, "dec": 12,
}
# « 21 sept. à 18-34 », ou « 19 févr., 14.03 » dans les versions
# récentes : le nom que l'enregistreur de l'iPhone et du Mac donne à ses
# fichiers.
VOICE_MEMO = re.compile(r"(\d{1,2}) ([a-zéû]+)\.?(?:,| à) (\d{1,2})[-h:.](\d{2})", re.IGNORECASE)
# « 2026/03/12 10:00 » (Meet), « 2025-03-04 à 10.15.32 » (capture d'écran
# du Mac), « 2025-03-04 at 9.15.32 PM » (la même, en anglais).
ISO_DATE = re.compile(
    r"(20\d{2})[-/_.]?(\d{2})[-/_.]?(\d{2})"
    r"(?:(?:[ T_-]+|\s+(?:à|at)\s+)(\d{1,2})[-h:.]?(\d{2})(?:[-h:.]\d{2})?(?:\s*([AP]M))?)?",
    re.IGNORECASE,
)
# « benjamin dotte_10-28-25_0514PM.amr » : l'enregistreur d'appels du
# téléphone, mois d'abord, à l'américaine.
CALL_RECORDER = re.compile(r"_(\d{2})-(\d{2})-(\d{2})_(\d{2})(\d{2})([AP]M)\b", re.IGNORECASE)
# Ce que l'ancienne app macOS laissait derrière elle en transcrivant : la
# piste extraite, sa version sans silences, ses morceaux. Pas une réunion
# de plus — au mieux, la seule trace audio d'une réunion déjà là. Odoo,
# lui, nomme « audio » tout court les messages vocaux de ses discussions.
ARTIFACT = re.compile(r"^audio(?:(?:\.vad|_partie_\d+)?\.(?:wav|m4a|mp3|flac))?$", re.IGNORECASE)
# Les caractères invisibles que l'iPhone glisse dans ses noms (« 14.03\u200b »)
# ou qui entourent un numéro de téléphone (« \u202a03 27… \u202c »).
INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
MIN_MEETING_SECONDS = 120


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn"
    )


def _clean(name: str) -> str:
    """Le nom tel que les règles le lisent. Le Mac écrit ses noms en
    Unicode décomposé — « à » y devient « a » suivi d'un accent — et
    l'iPhone y glisse des caractères invisibles : sans ce passage, ni
    « à 10.15 » ni « réunion » ne se reconnaissent."""
    return INVISIBLE.sub("", unicodedata.normalize("NFC", name))


def stem(name: str) -> str:
    """Le nom qui reste d'un fichier quand on retire ce que les copies y
    ajoutent : extension, « _compressed », « (1) »."""
    base = PurePosixPath(name).stem if "." in name else name
    base = _fold(base)
    base = re.sub(r"[ _-]*(compress(e|ed|ee)?|copie|copy)$", "", base)
    base = re.sub(r"\s*\(\d+\)$", "", base)
    return re.sub(r"[\s_]+", " ", base).strip()


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def recording_date(file: dict[str, Any]) -> tuple[str, bool]:
    """La date de la réunion, et si elle vient du nom (sûre) ou de Drive
    (approchée).

    Drive date un fichier de son dépôt, pas de son enregistrement : un
    mémo vocal envoyé trois jours après porte la date de l'envoi. Le nom,
    quand il en porte une, est plus fiable.
    """
    name = _clean(str(file.get("name") or ""))
    reference = min(
        (d for d in (_parse_iso(file.get("createdTime", "")), _parse_iso(file.get("modifiedTime", ""))) if d),
        default=None,
    )
    memo = VOICE_MEMO.search(name)
    if memo:
        jour, mois_nom, heure, minute = memo.groups()
        mois = MONTHS.get(_fold(mois_nom)[:5]) or MONTHS.get(_fold(mois_nom)[:4]) or MONTHS.get(_fold(mois_nom)[:3])
        if mois:
            annee = (reference or datetime.now(timezone.utc)).year
            try:
                date = datetime(annee, mois, int(jour), int(heure), int(minute))
                # Un « 21 déc. » déposé en janvier est de l'année d'avant.
                if reference and date.replace(tzinfo=None) > reference.replace(tzinfo=None) + timedelta(days=2):
                    date = date.replace(year=annee - 1)
                return date.isoformat(timespec="minutes"), True
            except ValueError:
                pass
    iso = ISO_DATE.search(name)
    if iso:
        a, m, j, h, mi, meridien = iso.groups()
        try:
            date = datetime(int(a), int(m), int(j), _hour(h, meridien), int(mi or 0))
            return date.isoformat(timespec="minutes"), True
        except ValueError:
            pass
    appel = CALL_RECORDER.search(name)
    if appel:
        m, j, a, h, mi, meridien = appel.groups()
        try:
            date = datetime(2000 + int(a), int(m), int(j), _hour(h, meridien), int(mi))
            return date.isoformat(timespec="minutes"), True
        except ValueError:
            pass
    if reference:
        # Heure de Paris, pas celle du serveur : le conteneur vit en UTC.
        return reference.astimezone(PARIS).replace(tzinfo=None).isoformat(timespec="minutes"), False
    return "", False


def _hour(heure: str | None, meridien: str | None) -> int:
    """L'heure sur 24 h, que le nom la donne sur 24 h ou sur 12 h."""
    h = int(heure or 0)
    if meridien:
        h = h % 12 + (12 if meridien.upper() == "PM" else 0)
    return h


def duration_seconds(file: dict[str, Any]) -> float | None:
    millis = (file.get("videoMediaMetadata") or {}).get("durationMillis")
    return float(millis) / 1000 if millis else None


def classify(file: dict[str, Any]) -> str:
    """« meeting », « unsure » ou « other » — une proposition, pas un tri."""
    name = _clean(str(file.get("name") or ""))
    if NOT_MEETING.search(name) or ARTIFACT.match(name):
        return "other"
    duree = duration_seconds(file)
    if duree is not None and duree < MIN_MEETING_SECONDS:
        return "other"
    if MEETING_HINTS.search(name) or VOICE_MEMO.search(name):
        return "meeting"
    # Un fichier audio, c'est presque toujours un enregistrement de
    # réunion ; une vidéo peut être n'importe quoi.
    return "meeting" if str(file.get("mimeType", "")).startswith("audio/") else "unsure"


def library_match(file: dict[str, Any], date: str, library: list[dict[str, Any]]) -> dict[str, Any] | None:
    """La réunion déjà dans transcript qui correspond à ce fichier, si on
    la reconnaît : même nom, et même durée ou même période. Le nom seul ne
    suffit pas — « Nouvel enregistrement 9 » revient d'une année sur
    l'autre."""
    racine = stem(str(file.get("name") or ""))
    if not racine:
        return None
    duree = duration_seconds(file)
    quand = _parse_iso(date)
    for job in library:
        if stem(str(job.get("filename") or "")) != racine:
            continue
        if duree and job.get("duration_seconds") and abs(float(job["duration_seconds"]) - duree) <= 3:
            return job
        if file.get("size") and job.get("video_bytes") and int(file["size"]) == int(job["video_bytes"]):
            return job
        date_job = _parse_iso(str(job.get("quand") or ""))
        if quand and date_job and abs((quand.replace(tzinfo=None) - date_job.replace(tzinfo=None)).days) <= 3:
            return job
    return None


def same_file_key(name: str, size: int | str | None) -> tuple[str, int] | None:
    """Ce qui fait de deux fichiers le même enregistrement quand leurs
    empreintes diffèrent : même nom une fois les ajouts des copies retirés,
    même taille à l'octet près. Drive recalcule parfois l'empreinte d'un
    fichier redéposé ; deux réunions distinctes, elles, n'ont jamais
    exactement la même taille."""
    racine, taille = stem(name), int(size or 0)
    return (racine, taille) if racine and taille else None


def recovered_by_name(recovered: dict[str, dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    """Les fichiers déjà récupérés, rangés par nom et taille."""
    index: dict[tuple[str, int], dict[str, Any]] = {}
    for row in recovered.values():
        cle = same_file_key(str(row.get("name") or ""), row.get("size_bytes"))
        if cle and cle not in index:
            index[cle] = row
    return index


def build_inventory(
    files: list[dict[str, Any]],
    *,
    user_id: int,
    shared_drives: dict[str, str],
    recovered: dict[str, dict[str, Any]],
    recovered_checksums: dict[str, dict[str, Any]],
    library: list[dict[str, Any]],
    excluded_drives: set[str],
) -> list[dict[str, Any]]:
    """L'inventaire tel qu'on le montre : du plus récent au plus ancien, un
    statut par fichier, et jamais deux lignes pour le même contenu."""
    items: list[dict[str, Any]] = []
    vus: dict[str, str] = {}
    vus_nom: dict[tuple[str, int], str] = {}
    recuperes_nom = recovered_by_name(recovered)
    # Les plus anciens d'abord pour le dédoublonnage : la copie qu'on garde
    # est l'originale, pas celle déposée une seconde fois.
    for file in sorted(files, key=lambda f: f.get("createdTime", "")):
        if file.get("driveId") in excluded_drives:
            continue
        date, date_sure = recording_date(file)
        # Drive donne un MD5, Odoo un SHA-1 : les deux ne se confondent
        # jamais, et chacun dédoublonne sa source.
        checksum = file.get("md5Checksum") or file.get("checksum") or None
        item: dict[str, Any] = {
            "id": file["id"],
            "name": file.get("name", ""),
            "mime_type": file.get("mimeType", ""),
            "size": int(file.get("size") or 0),
            "checksum": checksum,
            "recorded_at": date,
            "recorded_at_from_name": date_sure,
            "duration_seconds": duration_seconds(file),
            "location": file.get("location") or _location(file, shared_drives),
            "web_link": file.get("webViewLink", ""),
            "kind": classify(file),
            "status": "new",
        }
        cle = same_file_key(item["name"], item["size"])
        deja = (
            recovered.get(file["id"])
            or (recovered_checksums.get(checksum) if checksum else None)
            or (recuperes_nom.get(cle) if cle else None)
        )
        if deja:
            item["status"] = "recovered"
            item["recovered_by"] = deja.get("user_email", "")
            if deja.get("user_id") == user_id and deja.get("job_id"):
                item["job_id"] = deja["job_id"]
        elif (checksum and checksum in vus) or (cle and cle in vus_nom):
            item["status"] = "duplicate"
            item["duplicate_of"] = vus[checksum] if checksum in vus else vus_nom[cle]
        else:
            job = library_match(file, date, library)
            if job:
                item["status"] = "in_library"
                if job.get("owner_id") == user_id:
                    item["job_id"] = job["id"]
        if checksum and checksum not in vus:
            vus[checksum] = file["id"]
        if cle and cle not in vus_nom:
            vus_nom[cle] = file["id"]
        items.append(item)
    items.sort(key=lambda i: i["recorded_at"], reverse=True)
    return items


def _location(file: dict[str, Any], shared_drives: dict[str, str]) -> dict[str, str]:
    if file.get("driveId"):
        return {"kind": "shared_drive", "name": shared_drives.get(file["driveId"], "Drive partagé")}
    proprietaire = (file.get("owners") or [{}])[0]
    if proprietaire.get("me"):
        return {"kind": "my_drive", "name": "Mon Drive"}
    return {"kind": "shared_with_me", "name": proprietaire.get("emailAddress", "")}


# Où vivent les pièces jointes d'Odoo, dit comme la personne le dit.
ODOO_PLACES = {
    **{modele: libelle for modele, (libelle, _) in OdooGateway.MODELES.items()},
    "discuss.channel": "discussion",
    "helpdesk.ticket": "ticket",
    "project.update": "point d'avancement",
}


def odoo_file(piece: dict[str, Any], odoo_url: str) -> dict[str, Any]:
    """Une pièce jointe d'Odoo, sous la forme d'un fichier de l'inventaire.

    Odoo date en UTC, sans le dire ; la date de dépôt sert comme celle du
    Drive, faute de mieux dans le nom."""
    modele, fiche = str(piece.get("res_model") or ""), int(piece.get("res_id") or 0)
    base = odoo_url.rstrip("/")
    lien = ""
    if base and fiche:
        lien = (f"{base}/odoo/discuss?active_id=discuss.channel_{fiche}" if modele == "discuss.channel"
                else f"{base}/odoo/{modele}/{fiche}")
    depot = str(piece.get("create_date") or "").replace(" ", "T")
    return {
        "id": str(piece["id"]),
        "name": piece.get("name") or "",
        "mimeType": piece.get("mimetype") or "",
        "size": piece.get("file_size") or 0,
        "checksum": piece.get("checksum") or None,
        "createdTime": f"{depot}Z" if depot else "",
        "webViewLink": lien,
        "location": {
            "kind": "odoo",
            "name": " · ".join(x for x in (ODOO_PLACES.get(modele, modele), piece.get("res_name") or "") if x),
        },
    }


def odoo_record(piece: dict[str, Any]) -> tuple[str, int] | None:
    """La fiche à laquelle la réunion récupérée se rattache : celle où
    l'enregistrement était joint — une discussion n'en est pas une."""
    modele, fiche = str(piece.get("res_model") or ""), int(piece.get("res_id") or 0)
    return (modele, fiche) if modele in OdooGateway.MODELES and fiche else None


def odoo_moment(date: Any) -> str:
    """Une date d'Odoo — UTC, sans le dire — sous la forme qu'attend
    `recording_date`."""
    texte = str(date or "").replace(" ", "T")
    return f"{texte}Z" if texte else ""


def note_excerpt(note: dict[str, Any], longueur: int = 160) -> str:
    """De quoi reconnaître une note sans l'ouvrir : son en-tête s'il y en
    a un, sinon le début du texte."""
    texte = " ".join((note["header"] or note["text"]).split())
    return texte if len(texte) <= longueur else texte[:longueur].rsplit(" ", 1)[0] + " …"


def build_note_inventory(
    messages: list[dict[str, Any]],
    *,
    user_id: int,
    recovered: dict[str, dict[str, Any]],
    library: list[dict[str, Any]],
    odoo_url: str,
) -> list[dict[str, Any]]:
    """Les transcriptions collées dans Odoo, chacune avec son statut.

    Une note est reconnue par son texte, pas par son nom : celle que
    transcript a déposée, celle déjà récupérée, celle dont la réunion est
    déjà dans la bibliothèque — même transcrite par un autre moteur — et
    celle collée deux fois ne sont jamais proposées comme nouvelles."""
    base = odoo_url.rstrip("/")
    deposees = {int(j["odoo_message_id"]): j for j in library if j.get("odoo_message_id")}
    vues: list[tuple[str, frozenset[int]]] = []
    items: list[dict[str, Any]] = []
    for message in sorted(messages, key=lambda m: str(m.get("date") or "")):
        note = read_note(message)
        ident = str(message["id"])
        modele, fiche = str(message.get("model") or ""), int(message.get("res_id") or 0)
        date, _ = recording_date({"createdTime": odoo_moment(message.get("date"))})
        item: dict[str, Any] = {
            "id": ident,
            "name": note["title"],
            "excerpt": note_excerpt(note),
            "recorded_at": date,
            "recorded_at_from_name": False,
            "words": len(words(note["text"])),
            "author": author_name(message),
            "kind": note["kind"],
            "location": {
                "kind": "odoo",
                "name": " · ".join(x for x in (ODOO_PLACES.get(modele, modele), message.get("record_name") or "") if x),
            },
            "web_link": f"{base}/odoo/{modele}/{fiche}" if base and fiche else "",
            "status": "new",
        }
        deja = recovered.get(ident)
        deposee = deposees.get(int(message["id"]))
        if deja:
            item["status"] = "recovered"
            item["recovered_by"] = deja.get("user_email", "")
            if deja.get("user_id") == user_id and deja.get("job_id"):
                item["job_id"] = deja["job_id"]
        elif deposee:
            item["status"] = "published"
            if deposee.get("owner_id") == user_id:
                item["job_id"] = deposee["id"]
        else:
            job = best_match(note["fingerprint"], library)
            double = next((i for i, fp in vues if overlap(note["fingerprint"], fp) >= SAME_MEETING), None)
            if job and job.get("owner_id") == user_id:
                item["status"] = "in_library"
                item["job_id"] = job["id"]
            elif job:
                item["status"] = "colleague"
                item["recovered_by"] = job.get("owner_email", "")
            elif double:
                item["status"] = "duplicate"
                item["duplicate_of"] = double
        vues.append((ident, note["fingerprint"]))
        items.append(item)
    items.sort(key=lambda i: i["recorded_at"], reverse=True)
    return items


class DriveImport(BaseModel):
    trash_original: bool = False


class DriveAttach(BaseModel):
    job_id: int
    trash_original: bool = False


def register_recovery_routes(
    app: FastAPI,
    *,
    db,
    config,
    coffre: Coffre,
    current_user: Callable[..., int],
    human_user: Callable[..., int],
    storage: Callable[[], Any],
    google_secret: Callable[[], str],
    odoo_for: Callable[[int], OdooGateway],
    oauth_opener: Callable[..., Any] | None = None,
) -> None:
    oauth = GoogleOAuth(
        client_id=config.google_client_id,
        client_secret=google_secret,
        redirect_uri=f"{config.public_url.rstrip('/')}/api/google/callback",
        domain=config.google_domain,
        opener=oauth_opener,
    )

    def refresh_token_for(user_id: int) -> str:
        compte = db.google_account(user_id)
        return coffre.dechiffrer(compte["refresh_token_enc"]) if compte else ""

    tokens = AccessTokens(oauth, refresh_token_for)

    def drive_for(user_id: int) -> UserDrive:
        return UserDrive(lambda: tokens.for_user(user_id), opener=oauth_opener)

    secret_failure = {"until": 0.0}

    def secret_ready() -> bool:
        """Le secret du client est-il lisible au coffre ? Sans lui, la
        connexion échouerait au retour de Google : autant ne pas la
        proposer. Un échec est retenu cinq minutes, pour ne pas solliciter
        le broker à chaque affichage."""
        if time.monotonic() < secret_failure["until"]:
            return False
        try:
            return bool(google_secret())
        except Exception as exc:  # noqa: BLE001 — broker, réseau, élément absent
            log.info("secret du client Google illisible : %s", exc)
            secret_failure["until"] = time.monotonic() + 300
            return False

    def google_status(user_id: int) -> dict[str, Any]:
        compte = db.google_account(user_id)
        return {
            "available": oauth.configured and coffre.disponible and secret_ready(),
            "connected": bool(compte),
            "email": compte["email"] if compte else "",
        }

    def enabled_for(user_id: int) -> bool:
        return "*" in config.recovery_users or db.email_for_user(user_id).lower() in config.recovery_users

    def require_enabled(user_id: int) -> None:
        if not enabled_for(user_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Fonction non disponible.")

    @app.get("/api/google")
    def google_account(owner_id: int = Depends(current_user)) -> dict:
        return google_status(owner_id)

    @app.get("/api/google/connect")
    def google_connect(owner_id: int = Depends(human_user)) -> Response:
        require_enabled(owner_id)
        if not oauth.configured:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Connexion Google non configurée.")
        state = secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        db.save_oauth_state(state, owner_id, verifier)
        return RedirectResponse(
            oauth.authorization_url(state, challenge, login_hint=db.email_for_user(owner_id)),
            status_code=status.HTTP_302_FOUND,
        )

    @app.get("/api/google/callback")
    def google_callback(
        request: Request, state: str = "", code: str = "", error: str = "",
        owner_id: int = Depends(human_user),
    ) -> Response:
        """Le retour de Google. Toujours une redirection vers l'interface,
        qui dit ce qui s'est passé : une page d'erreur JSON au milieu d'un
        parcours de connexion ne dirait rien à personne."""
        def retour(resultat: str) -> Response:
            return RedirectResponse(f"/?recovery={resultat}", status_code=status.HTTP_302_FOUND)

        require_enabled(owner_id)
        verifier = db.pop_oauth_state(state, owner_id) if state else None
        if error or not code or not verifier:
            return retour("refused" if error else "expired")
        try:
            reponse = oauth.exchange(code, verifier)
        except GoogleUnavailable as exc:
            log.warning("connexion Google : %s", exc)
            return retour("failed")
        email = email_from_id_token(str(reponse.get("id_token") or ""))
        # Le Drive connecté doit être celui de la personne : relier le
        # compte d'un autre ferait récupérer — et retirer — ses fichiers
        # à sa place.
        if email != db.email_for_user(owner_id).lower():
            if reponse.get("refresh_token"):
                oauth.revoke(str(reponse["refresh_token"]))
            return retour("wrong_account")
        rafraichissement = str(reponse.get("refresh_token") or "")
        if not rafraichissement:
            return retour("failed")
        try:
            db.save_google_account(owner_id, email, coffre.chiffrer(rafraichissement),
                                   str(reponse.get("scope") or ""))
        except CoffreIndisponible:
            return retour("failed")
        tokens.forget(owner_id)
        return retour("connected")

    @app.delete("/api/google", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
    def google_disconnect(owner_id: int = Depends(human_user)) -> Response:
        rafraichissement = refresh_token_for(owner_id)
        if rafraichissement:
            oauth.revoke(rafraichissement)
        db.delete_google_account(owner_id)
        tokens.forget(owner_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/recovery")
    def recovery_state(owner_id: int = Depends(current_user)) -> dict:
        if not enabled_for(owner_id):
            return {"enabled": False, "prompt": False}
        google = google_status(owner_id)
        stockage_pret = storage_available()
        return {
            "enabled": True,
            # L'invitation ne s'affiche que si le parcours peut aller au
            # bout : sinon elle mènerait à « pas encore configuré ».
            "prompt": google["available"] and stockage_pret and not db.recovery_dismissed(owner_id),
            "google": google,
            "storage": stockage_pret,
            "odoo": odoo_for(owner_id).configured,
        }

    def storage_available() -> bool:
        try:
            storage()
            return True
        except StockageIndisponible:
            return False

    @app.post("/api/recovery/dismiss", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
    def recovery_dismiss(owner_id: int = Depends(human_user)) -> Response:
        db.dismiss_recovery(owner_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/recovery/drive")
    def drive_inventory(owner_id: int = Depends(human_user)) -> dict:
        require_enabled(owner_id)
        if not db.google_account(owner_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "Connecte d'abord ton Google Drive.")
        drive = drive_for(owner_id)
        try:
            partages = drive.shared_drives()
            fichiers = drive.media_files()
        except GoogleUnavailable as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        items = build_inventory(
            fichiers,
            user_id=owner_id,
            shared_drives=partages,
            recovered=db.recovered_sources("drive"),
            recovered_checksums=db.recovered_checksums(),
            library=db.library_fingerprints(),
            # Le stockage de transcript n'est pas un endroit d'où récupérer.
            excluded_drives={config.video_dossier} if config.video_dossier else set(),
        )
        return {"items": items}

    @app.post("/api/recovery/drive/{file_id}")
    def drive_import(file_id: str, payload: DriveImport, owner_id: int = Depends(human_user)) -> dict:
        """Récupère un fichier : une réunion à la date de l'enregistrement,
        sa vidéo en stockage froid, et l'original à la corbeille si demandé.

        Un fichier à la fois : la copie se fait chez Google et prend
        quelques secondes, l'interface avance ligne par ligne et montre
        chaque résultat."""
        require_enabled(owner_id)
        if db.recovered_sources("drive").get(file_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "Ce fichier a déjà été récupéré.")
        try:
            stockage = storage()
        except StockageIndisponible as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        drive = drive_for(owner_id)
        try:
            fichier = drive.file(file_id)
        except GoogleUnavailable as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        checksum = fichier.get("md5Checksum") or None
        if checksum and db.recovered_checksums().get(checksum):
            raise HTTPException(status.HTTP_409_CONFLICT, "Le même contenu a déjà été récupéré.")
        cle = same_file_key(str(fichier.get("name") or ""), fichier.get("size"))
        if cle and cle in recovered_by_name(db.recovered_sources("drive")):
            raise HTTPException(status.HTTP_409_CONFLICT, "Le même fichier a déjà été récupéré.")

        date, _ = recording_date(fichier)
        taille = int(fichier.get("size") or 0)
        job_id = db.create_job(
            owner_id=owner_id, filename=fichier.get("name", file_id),
            duration_seconds=duration_seconds(fichier) or 0, model="", language="fr",
            context={"recovered_from": "drive"}, chunks=[],
        )
        try:
            copy_video(drive, stockage, file_id, fichier, job_id)
        except HTTPException:
            db.supprimer_job(job_id)
            raise
        db.set_meeting_date(job_id, date or None)
        db.set_job_status(job_id, "recovered")
        db.record_recovered(
            source="drive", external_id=file_id, checksum=checksum, size_bytes=taille,
            name=fichier.get("name", ""), job_id=job_id, user_id=owner_id,
        )
        corbeille = trash_original(drive, file_id) if payload.trash_original else "not_requested"
        return {"job_id": job_id, "original": corbeille, "recorded_at": date}

    @app.post("/api/recovery/drive/{file_id}/attach")
    def drive_attach(file_id: str, payload: DriveAttach, owner_id: int = Depends(human_user)) -> dict:
        """Range un fichier avec la réunion déjà transcrite qu'il
        enregistre, au lieu d'en créer une seconde.

        Une réunion transcrite par l'app macOS n'a souvent pas gardé sa
        vidéo : celle du Drive la rejoint, en stockage froid. Si elle en a
        déjà une, rien n'est copié — et l'original ne part à la corbeille
        que s'il est, à l'octet près, celui qu'on garde."""
        require_enabled(owner_id)
        if db.recovered_sources("drive").get(file_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "Ce fichier a déjà été récupéré.")
        job = db.get_job(payload.job_id)
        if not job or job["owner_id"] != owner_id or job["deleted_at"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Réunion introuvable.")
        drive = drive_for(owner_id)
        try:
            fichier = drive.file(file_id)
        except GoogleUnavailable as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        taille = int(fichier.get("size") or 0)

        if job["video_file_id"]:
            video = "kept"
            verifie = bool(taille) and int(job["video_bytes"] or 0) == taille
        else:
            try:
                stockage = storage()
            except StockageIndisponible as exc:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
            copy_video(drive, stockage, file_id, fichier, job["id"])
            video, verifie = "attached", True
        date, depuis_le_nom = recording_date(fichier)
        if depuis_le_nom and not job["meeting_date"]:
            db.set_meeting_date(job["id"], date)
        db.record_recovered(
            source="drive", external_id=file_id, checksum=fichier.get("md5Checksum") or None,
            size_bytes=taille, name=fichier.get("name", ""), job_id=job["id"], user_id=owner_id,
        )
        if not payload.trash_original:
            corbeille = "not_requested"
        elif verifie:
            corbeille = trash_original(drive, file_id)
        else:
            corbeille = "kept_different"
        return {"job_id": job["id"], "video": video, "original": corbeille}

    def copy_video(drive: UserDrive, stockage, file_id: str, fichier: dict[str, Any], job_id: int) -> None:
        """Copie un fichier du Drive vers le stockage de transcript, chez
        Google, et le donne pour vidéo à la réunion — seulement si la
        copie a la taille de l'original."""
        taille = int(fichier.get("size") or 0)
        droit = ""
        try:
            droit = drive.grant_reader(file_id, config.gcp_compte)
            extension = PurePosixPath(fichier.get("name", "")).suffix or ""
            copie = stockage.copy_from(file_id, f"transcript-{job_id}{extension}")
            if taille and int(copie.get("size") or 0) != taille:
                stockage.supprimer(str(copie.get("id") or ""))
                raise StockageIndisponible("La copie n'a pas la taille de l'original.")
        except (GoogleUnavailable, StockageIndisponible) as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Copie impossible : {exc}") from exc
        finally:
            # Le droit de lecture n'était que le temps de la copie.
            if droit:
                try:
                    drive.revoke_permission(file_id, droit)
                except GoogleUnavailable as exc:
                    log.warning("droit temporaire non retiré sur %s : %s", file_id, exc)
        db.ouvrir_envoi_video(job_id, "", taille)
        db.terminer_envoi_video(job_id, str(copie["id"]))

    def trash_original(drive: UserDrive, file_id: str) -> str:
        try:
            drive.trash(file_id)
            db.mark_original_trashed("drive", file_id)
            return "trashed"
        except GoogleUnavailable as exc:
            # Copie faite, original gardé : rien n'est perdu, on le dit.
            log.info("original gardé (%s) : %s", file_id, exc)
            return "kept"

    # -- Odoo ---------------------------------------------------------------

    def odoo_ready(owner_id: int) -> OdooGateway:
        require_enabled(owner_id)
        odoo = odoo_for(owner_id)
        if not odoo.configured:
            raise HTTPException(status.HTTP_409_CONFLICT, "Enregistre d'abord ta clé Odoo dans Réglages.")
        return odoo

    @app.get("/api/recovery/odoo")
    def odoo_inventory(owner_id: int = Depends(human_user)) -> dict:
        odoo = odoo_ready(owner_id)
        try:
            pieces = odoo.media_attachments()
        except OdooUnavailable as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        items = build_inventory(
            [odoo_file(p, config.odoo_url) for p in pieces],
            user_id=owner_id,
            shared_drives={},
            recovered=db.recovered_sources("odoo"),
            recovered_checksums=db.recovered_checksums(),
            library=db.library_fingerprints(),
            excluded_drives=set(),
        )
        return {"items": items}

    def odoo_piece(odoo: OdooGateway, attachment_id: int) -> dict[str, Any]:
        try:
            return odoo.attachment(attachment_id, contenu=True)
        except OdooUnavailable as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    @app.post("/api/recovery/odoo/{attachment_id}")
    def odoo_import(attachment_id: int, owner_id: int = Depends(human_user)) -> dict:
        """Récupère une pièce jointe d'Odoo : une réunion à sa date, son
        enregistrement en stockage froid, et rattachée à la fiche où il
        était joint.

        L'original reste sur sa fiche : il fait partie du dossier, et
        Odoo n'a pas de corbeille d'où le rattraper."""
        odoo = odoo_ready(owner_id)
        if db.recovered_sources("odoo").get(str(attachment_id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Ce fichier a déjà été récupéré.")
        try:
            stockage = storage()
        except StockageIndisponible as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        piece = odoo_piece(odoo, attachment_id)
        fichier = odoo_file(piece, config.odoo_url)
        if fichier["checksum"] and db.recovered_checksums().get(fichier["checksum"]):
            raise HTTPException(status.HTTP_409_CONFLICT, "Le même contenu a déjà été récupéré.")
        cle = same_file_key(fichier["name"], fichier["size"])
        if cle and cle in recovered_by_name(db.recovered_sources("odoo")):
            raise HTTPException(status.HTTP_409_CONFLICT, "Le même fichier a déjà été récupéré.")

        date, _ = recording_date(fichier)
        job_id = db.create_job(
            owner_id=owner_id, filename=fichier["name"] or f"odoo-{attachment_id}",
            duration_seconds=0, model="", language="fr",
            context={"recovered_from": "odoo"}, chunks=[],
        )
        try:
            send_bytes(stockage, job_id, piece)
        except HTTPException:
            db.supprimer_job(job_id)
            raise
        db.set_meeting_date(job_id, date or None)
        db.set_job_status(job_id, "recovered")
        fiche = odoo_record(piece)
        if fiche:
            db.set_odoo_link(job_id, model=fiche[0], record_id=fiche[1], message_id=None)
        db.record_recovered(
            source="odoo", external_id=str(attachment_id), checksum=fichier["checksum"],
            size_bytes=len(piece["bytes"]), name=fichier["name"], job_id=job_id, user_id=owner_id,
        )
        return {"job_id": job_id, "original": "left_in_odoo", "linked": bool(fiche), "recorded_at": date}

    @app.post("/api/recovery/odoo/{attachment_id}/attach")
    def odoo_attach(attachment_id: int, payload: DriveAttach, owner_id: int = Depends(human_user)) -> dict:
        """Range une pièce jointe avec la réunion déjà transcrite qu'elle
        enregistre. La réunion gagne l'enregistrement si elle n'en avait
        pas, et la fiche si elle n'était liée à aucune."""
        odoo = odoo_ready(owner_id)
        if db.recovered_sources("odoo").get(str(attachment_id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Ce fichier a déjà été récupéré.")
        job = db.get_job(payload.job_id)
        if not job or job["owner_id"] != owner_id or job["deleted_at"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Réunion introuvable.")
        if job["video_file_id"]:
            piece = odoo_piece_meta(odoo, attachment_id)
            video = "kept"
        else:
            try:
                stockage = storage()
            except StockageIndisponible as exc:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
            piece = odoo_piece(odoo, attachment_id)
            send_bytes(stockage, job["id"], piece)
            video = "attached"
        fichier = odoo_file(piece, config.odoo_url)
        date, depuis_le_nom = recording_date(fichier)
        if depuis_le_nom and not job["meeting_date"]:
            db.set_meeting_date(job["id"], date)
        fiche = odoo_record(piece)
        if fiche and not job["odoo_model"]:
            db.set_odoo_link(job["id"], model=fiche[0], record_id=fiche[1], message_id=None)
        db.record_recovered(
            source="odoo", external_id=str(attachment_id), checksum=fichier["checksum"],
            size_bytes=int(fichier["size"] or 0), name=fichier["name"], job_id=job["id"], user_id=owner_id,
        )
        return {"job_id": job["id"], "video": video, "original": "left_in_odoo"}

    def odoo_piece_meta(odoo: OdooGateway, attachment_id: int) -> dict[str, Any]:
        try:
            return odoo.attachment(attachment_id)
        except OdooUnavailable as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    def send_bytes(stockage, job_id: int, piece: dict[str, Any]) -> None:
        """Envoie au stockage un enregistrement déjà en mémoire, par
        morceaux, et le donne pour vidéo à la réunion."""
        octets: bytes = piece["bytes"]
        if not octets:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Odoo a rendu une pièce jointe vide.")
        extension = PurePosixPath(str(piece.get("name") or "")).suffix or ""
        try:
            session = stockage.ouvrir_envoi(
                f"transcript-{job_id}{extension}", len(octets), piece.get("mimetype") or "application/octet-stream",
            )
            fichier_id = None
            for debut in range(0, len(octets), MORCEAU):
                fichier_id = stockage.envoyer_morceau(session, debut, octets[debut:debut + MORCEAU], len(octets))
        except StockageIndisponible as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Copie impossible : {exc}") from exc
        if not fichier_id:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Copie impossible : l'envoi n'a pas abouti.")
        db.ouvrir_envoi_video(job_id, "", len(octets))
        db.terminer_envoi_video(job_id, fichier_id)

    # -- Transcriptions collées dans Odoo ------------------------------------

    empreintes: dict[int, tuple[str, frozenset[int]]] = {}

    def note_library() -> list[dict[str, Any]]:
        """La bibliothèque de toute l'équipe, chaque réunion avec
        l'empreinte de son texte. Les empreintes sont gardées d'un
        inventaire à l'autre et recalculées pour les seules réunions
        modifiées depuis."""
        connues = {i: v[0] for i, v in empreintes.items()}
        reunions = db.library_transcripts(connues)
        for reunion in reunions:
            if "transcript" in reunion:
                empreintes[reunion["id"]] = (reunion["updated_at"], fingerprint(reunion["transcript"]))
            reunion["fingerprint"] = empreintes[reunion["id"]][1]
        for disparue in set(empreintes) - {r["id"] for r in reunions}:
            empreintes.pop(disparue, None)
        return reunions

    def odoo_note(odoo: OdooGateway, message_id: int) -> dict[str, Any]:
        try:
            return odoo.transcript_note(message_id)
        except OdooUnavailable as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    @app.get("/api/recovery/odoo-notes")
    def odoo_notes_inventory(owner_id: int = Depends(human_user)) -> dict:
        odoo = odoo_ready(owner_id)
        try:
            messages = odoo.transcript_notes()
        except OdooUnavailable as exc:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
        items = build_note_inventory(
            messages,
            user_id=owner_id,
            recovered=db.recovered_sources("odoo_note"),
            library=note_library(),
            odoo_url=config.odoo_url,
        )
        return {"items": items}

    @app.post("/api/recovery/odoo-notes/{message_id}")
    def odoo_note_import(message_id: int, owner_id: int = Depends(human_user)) -> dict:
        """Récupère une transcription collée dans Odoo : une réunion
        terminée, à la date de la note, rattachée à sa fiche.

        La réunion est liée à la note elle-même : transcript la sait déjà
        dans Odoo et ne proposera pas de l'y déposer une seconde fois. La
        note, elle, reste où elle est."""
        odoo = odoo_ready(owner_id)
        if db.recovered_sources("odoo_note").get(str(message_id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Cette transcription a déjà été récupérée.")
        message = odoo_note(odoo, message_id)
        note = read_note(message)
        bibliotheque = note_library()
        if any(j.get("odoo_message_id") == message_id for j in bibliotheque) or best_match(
            note["fingerprint"], bibliotheque
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, "Cette transcription est déjà dans la bibliothèque.")
        repliques = note["segments"]
        if not repliques:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cette note ne contient aucun texte à récupérer.")

        modele, fiche = str(message.get("model") or ""), int(message.get("res_id") or 0)
        date, _ = recording_date({"createdTime": odoo_moment(message.get("date"))})
        voix = sorted({r["speaker"] for r in repliques if r["speaker"]})
        job_id = db.create_job(
            owner_id=owner_id, filename=str(message.get("record_name") or note["title"]),
            duration_seconds=max(r["start"] for r in repliques), model="", language="fr",
            context={"recovered_from": "odoo_note", "odoo_note_header": note["header"]}, chunks=[],
        )
        try:
            db.replace_segments(job_id, repliques)
            db.finish_job(
                job_id, title=note["title"], transcript=transcript_text(repliques),
                speakers={v: v for v in voix}, technical_terms=[], cost_usd=0,
            )
            db.set_meeting_date(job_id, date or None)
            if modele in OdooGateway.MODELES and fiche:
                db.set_odoo_link(job_id, model=modele, record_id=fiche, message_id=message_id)
            db.record_recovered(
                source="odoo_note", external_id=str(message_id), checksum=None,
                size_bytes=len(note["text"].encode()), name=note["title"], job_id=job_id, user_id=owner_id,
            )
        except Exception:
            db.supprimer_job(job_id)
            raise
        return {"job_id": job_id, "original": "left_in_odoo", "linked": bool(fiche), "recorded_at": date}

    @app.post("/api/recovery/odoo-notes/{message_id}/attach")
    def odoo_note_attach(message_id: int, payload: DriveAttach, owner_id: int = Depends(human_user)) -> dict:
        """Relie une transcription collée dans Odoo à la réunion déjà dans
        transcript qu'elle reprend : la réunion gagne sa fiche, et la note
        compte comme son dépôt."""
        odoo = odoo_ready(owner_id)
        if db.recovered_sources("odoo_note").get(str(message_id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Cette transcription a déjà été récupérée.")
        job = db.get_job(payload.job_id)
        if not job or job["owner_id"] != owner_id or job["deleted_at"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Réunion introuvable.")
        message = odoo_note(odoo, message_id)
        note = read_note(message)
        if overlap(note["fingerprint"], fingerprint(job["transcript"] or "")) < SAME_MEETING:
            raise HTTPException(status.HTTP_409_CONFLICT, "Cette note ne reprend pas la transcription de cette réunion.")
        modele, fiche = str(message.get("model") or ""), int(message.get("res_id") or 0)
        meme_fiche = (job["odoo_model"], job["odoo_record_id"]) == (modele, fiche)
        relie = False
        if modele in OdooGateway.MODELES and fiche and (
            not job["odoo_model"] or (meme_fiche and not job["odoo_message_id"])
        ):
            db.set_odoo_link(job["id"], model=modele, record_id=fiche, message_id=message_id)
            relie = True
        db.record_recovered(
            source="odoo_note", external_id=str(message_id), checksum=None,
            size_bytes=len(note["text"].encode()), name=note["title"], job_id=job["id"], user_id=owner_id,
        )
        return {"job_id": job["id"], "video": "kept", "original": "left_in_odoo", "linked": relie}
