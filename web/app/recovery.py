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
from .stockage import StockageIndisponible

log = logging.getLogger("ekovideo.web")

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
# « 21 sept. à 18-34 » : le nom que l'enregistreur de l'iPhone et du Mac
# donne à ses fichiers.
VOICE_MEMO = re.compile(r"(\d{1,2}) ([a-zéû]+)\.? à (\d{1,2})[-h:](\d{2})", re.IGNORECASE)
ISO_DATE = re.compile(r"(20\d{2})[-/_.]?(\d{2})[-/_.]?(\d{2})(?:[ T_-]+(\d{2})[-h:.]?(\d{2}))?")
MIN_MEETING_SECONDS = 120


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn"
    )


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
    name = str(file.get("name") or "")
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
        a, m, j, h, mi = iso.groups()
        try:
            date = datetime(int(a), int(m), int(j), int(h or 0), int(mi or 0))
            return date.isoformat(timespec="minutes"), True
        except ValueError:
            pass
    if reference:
        return reference.astimezone().replace(tzinfo=None).isoformat(timespec="minutes"), False
    return "", False


def duration_seconds(file: dict[str, Any]) -> float | None:
    millis = (file.get("videoMediaMetadata") or {}).get("durationMillis")
    return float(millis) / 1000 if millis else None


def classify(file: dict[str, Any]) -> str:
    """« meeting », « unsure » ou « other » — une proposition, pas un tri."""
    name = str(file.get("name") or "")
    if NOT_MEETING.search(name):
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
    # Les plus anciens d'abord pour le dédoublonnage : la copie qu'on garde
    # est l'originale, pas celle déposée une seconde fois.
    for file in sorted(files, key=lambda f: f.get("createdTime", "")):
        if file.get("driveId") in excluded_drives:
            continue
        date, date_sure = recording_date(file)
        checksum = file.get("md5Checksum") or None
        item: dict[str, Any] = {
            "id": file["id"],
            "name": file.get("name", ""),
            "mime_type": file.get("mimeType", ""),
            "size": int(file.get("size") or 0),
            "checksum": checksum,
            "recorded_at": date,
            "recorded_at_from_name": date_sure,
            "duration_seconds": duration_seconds(file),
            "location": _location(file, shared_drives),
            "web_link": file.get("webViewLink", ""),
            "kind": classify(file),
            "status": "new",
        }
        deja = recovered.get(file["id"]) or (recovered_checksums.get(checksum) if checksum else None)
        if deja:
            item["status"] = "recovered"
            item["recovered_by"] = deja.get("user_email", "")
            if deja.get("user_id") == user_id and deja.get("job_id"):
                item["job_id"] = deja["job_id"]
        elif checksum and checksum in vus:
            item["status"] = "duplicate"
            item["duplicate_of"] = vus[checksum]
        else:
            job = library_match(file, date, library)
            if job:
                item["status"] = "in_library"
                if job.get("owner_id") == user_id:
                    item["job_id"] = job["id"]
        if checksum and checksum not in vus:
            vus[checksum] = file["id"]
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


class DriveImport(BaseModel):
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

        date, _ = recording_date(fichier)
        taille = int(fichier.get("size") or 0)
        job_id = db.create_job(
            owner_id=owner_id, filename=fichier.get("name", file_id),
            duration_seconds=duration_seconds(fichier) or 0, model="", language="fr",
            context={"recovered_from": "drive"}, chunks=[],
        )
        droit = ""
        try:
            droit = drive.grant_reader(file_id, config.gcp_compte)
            extension = PurePosixPath(fichier.get("name", "")).suffix or ""
            copie = stockage.copy_from(file_id, f"transcript-{job_id}{extension}")
            if taille and int(copie.get("size") or 0) != taille:
                stockage.supprimer(str(copie.get("id") or ""))
                raise StockageIndisponible("La copie n'a pas la taille de l'original.")
        except (GoogleUnavailable, StockageIndisponible) as exc:
            db.supprimer_job(job_id)
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
        db.set_meeting_date(job_id, date or None)
        db.set_job_status(job_id, "recovered")
        db.record_recovered(
            source="drive", external_id=file_id, checksum=checksum, size_bytes=taille,
            name=fichier.get("name", ""), job_id=job_id, user_id=owner_id,
        )

        corbeille = "not_requested"
        if payload.trash_original:
            try:
                drive.trash(file_id)
                db.mark_original_trashed("drive", file_id)
                corbeille = "trashed"
            except GoogleUnavailable as exc:
                # Copie faite, original gardé : rien n'est perdu, on le dit.
                log.info("original gardé (%s) : %s", file_id, exc)
                corbeille = "kept"
        return {"job_id": job_id, "original": corbeille, "recorded_at": date}
