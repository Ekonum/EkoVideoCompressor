"""API de la webapp.

Le contrat tient en quatre routes, et son point non négociable est que
le **navigateur fait tout le travail média**. Le serveur ne reçoit que
des fenêtres audio de quelques Mo : le VPS n'a ni le stockage pour les
sources ni le CPU pour les encoder.

Deuxième contrainte de forme : Cloudflare coupe les requêtes vers
100 s, or transcrire 30 minutes d'audio prend souvent plus. L'envoi
d'une fenêtre répond donc **202 immédiatement** et la transcription
part en tâche de fond ; le navigateur suit l'avancement par ``GET``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cloud_transcription import (
    CLOUD_TRANSCRIPTION_MODELS,
    CloudChunkResult,
    CloudTranscriptionError,
    canonical_cloud_model_id,
    chunk_seconds_for_model,
    estimate_cloud_cost,
    merge_chunk_results,
    plan_audio_chunks,
    provider_for_model,
)

from .auth import AccessVerifier, AuthError
from .db import Database
from .secrets import GeminiKey, SecretError
from .settings import Settings
from .terms import replace_term
from .transcription import context_for_chunk, transcribe_chunk, transcript_text

log = logging.getLogger("ekovideo.web")

# Profil d'upload imposé au navigateur — un seul endroit, parce que le
# navigateur obéit au serveur plutôt que de décider.
#
# MP3 64 kbps mono 16 kHz, soit **exactement** ce que produit
# `build_cloud_audio_cmd` aujourd'hui. Deux raisons. Gemini documente
# ses formats audio (wav, mp3, aiff, aac, ogg, flac) et l'Opus n'y
# figure pas : l'accepterait-il en pratique ? je n'en sais rien, et le
# vérifier demande une vraie clé. Et à format identique, la
# transcription issue du navigateur se compare trait pour trait à celle
# de l'app macOS — c'est la vérification du jalon.
#
# L'Opus reste l'optimisation visée : ~10,7 Mo/heure mesuré en M0
# contre ~28 en MP3. Le jour où on le valide contre l'API, c'est cette
# constante qui change, et rien d'autre.
AUDIO_PROFILE = {
    "codec": "mp3",
    "container": "mp3",
    "sample_rate": 16000,
    "channels": 1,
    "bitrate": 64000,
}

# L'extension compte : `_audio_mime` (cloud_transcription) en déduit le
# type déclaré à Gemini, et tout ce qui n'est pas .mp3 part en audio/wav.
CHUNK_SUFFIX = ".mp3"

# Les appels sont du réseau, pas du CPU : une concurrence basse suffit
# et protège les 256 Mo du conteneur.
MAX_CONCURRENT_CHUNKS = 2

# Une fenêtre de 30 min pèse ~14 Mo en MP3 64 kbps (~5 Mo en Opus). La
# marge couvre un réglage plus généreux sans jamais approcher les 100 Mo
# du tunnel.
MAX_CHUNK_BYTES = 60 * 1024 * 1024


class JobRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    duration_seconds: float = Field(gt=0)
    model: str = Field(min_length=1)
    language: str = "fr"
    context: dict[str, Any] = Field(default_factory=dict)


class ContextPatch(BaseModel):
    """Édition partielle : un champ absent est laissé tel quel, pour qu'un
    formulaire qui n'affiche pas les termes ne les efface pas."""

    title: str | None = None
    speakers: dict[str, str] | None = None
    technical_terms: list[str] | None = None


class TermReplacement(BaseModel):
    old: str = Field(min_length=1)
    new: str = Field(min_length=1)


class FinalizeResponse(BaseModel):
    job_id: int
    title: str
    transcript: str
    speakers: dict[str, str]
    technical_terms: list[str]
    cost_usd: float


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    gemini_key: GeminiKey | None = None,
    verifier: AccessVerifier | None = None,
) -> FastAPI:
    config = settings or Settings.from_env()
    db = database or Database(config.db_path)
    keys = gemini_key or GeminiKey(
        url=config.broker_url,
        token=config.broker_token,
        item=config.broker_item,
        field=config.broker_field,
        static_key=config.dev_api_key,
    )
    access = verifier or AccessVerifier(config.access_team_domain, config.access_aud)
    if not access.configured and not config.dev_mode:
        raise RuntimeError(
            "Cloudflare Access n'est pas configuré (EKOVIDEO_ACCESS_TEAM_DOMAIN "
            "et EKOVIDEO_ACCESS_AUD) et le mode développement est désactivé : "
            "refus de démarrer sans authentification."
        )

    config.chunk_dir.mkdir(parents=True, exist_ok=True)
    # Le client est construit par Vite ; en production l'image Docker
    # embarque `dist`. En développement on lance plutôt `npm run dev`,
    # qui sert le client et relaie /api ici.
    static_dir = Path(__file__).resolve().parent.parent / "client" / "dist"
    app = FastAPI(title="EkoVideo", version="1.0")
    app.state.settings = config
    app.state.db = db
    app.state.keys = keys
    app.state.semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)
    # asyncio ne garde qu'une référence faible sur les tâches : sans ce
    # jeu, une transcription en cours peut être ramassée par le GC.
    app.state.tasks = set()

    # -- identité ------------------------------------------------------

    def current_user(request: Request) -> int:
        if config.dev_mode:
            return db.user_id_for_email(config.dev_user_email)
        token = request.headers.get("Cf-Access-Jwt-Assertion", "")
        try:
            email = access.email_from_token(token)
        except AuthError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
        return db.user_id_for_email(email)

    def owned_job(job_id: int, owner_id: int) -> dict[str, Any]:
        job = db.get_job(job_id)
        if job is None or int(job["owner_id"]) != owner_id:
            # Même réponse dans les deux cas : le job d'un collègue ne doit
            # pas être distinguable d'un job inexistant.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Traitement introuvable.")
        return job

    # -- routes --------------------------------------------------------

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def index():
        page = static_dir / "index.html"
        if not page.exists():
            # Message franc plutôt qu'un 404 opaque : l'oubli le plus
            # probable est simplement de n'avoir pas construit le client.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Client non construit : lancez « npm run build » dans web/client "
                "(ou « npm run dev » pour développer).",
            )
        return FileResponse(page)

    @app.post("/api/jobs", status_code=status.HTTP_201_CREATED)
    def create_job(payload: JobRequest, owner_id: int = Depends(current_user)) -> dict:
        # `cloud_model_entry` accepte volontairement un identifiant inconnu
        # — l'app macOS laisse saisir un modèle tout juste sorti — en le
        # facturant au tarif le plus cher. Ici le modèle vient d'une liste
        # fermée : une coquille doit être refusée, pas facturée au prix fort.
        model = canonical_cloud_model_id(payload.model)
        if model not in {entry["id"] for entry in CLOUD_TRANSCRIPTION_MODELS}:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Modèle inconnu : {payload.model!r}.",
            )

        # Garde-fou budget : avant le premier octet uploadé, pas après.
        estimate = estimate_cloud_cost(payload.duration_seconds, model)
        spent = db.month_spend_usd()
        if spent + estimate["cost_usd"] > config.monthly_budget_usd:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                f"Ce traitement coûterait environ {estimate['cost_usd']:.2f} $US et "
                f"dépasserait le plafond mensuel de l'équipe "
                f"({spent:.2f} / {config.monthly_budget_usd:.2f} $US déjà engagés).",
            )

        windows = plan_audio_chunks(
            payload.duration_seconds, chunk_seconds_for_model(model)
        )
        job_id = db.create_job(
            owner_id=owner_id,
            filename=payload.filename,
            duration_seconds=payload.duration_seconds,
            model=model,
            language=payload.language,
            context=payload.context,
            chunks=windows,
        )
        return {
            "job_id": job_id,
            "model": model,
            "estimated_cost_usd": estimate["cost_usd"],
            "chunks": [
                {"index": i, "start": start, "end": end}
                for i, (start, end) in enumerate(windows)
            ],
            "audio": AUDIO_PROFILE,
        }

    @app.put("/api/jobs/{job_id}/chunks/{index}", status_code=status.HTTP_202_ACCEPTED)
    async def upload_chunk(
        job_id: int, index: int, request: Request, owner_id: int = Depends(current_user)
    ) -> dict:
        job = owned_job(job_id, owner_id)
        chunks = {c["idx"]: c for c in db.chunks_for_job(job_id)}
        window = chunks.get(index)
        if window is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Fenêtre inconnue.")

        body = await request.body()
        if not body:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fenêtre audio vide.")
        if len(body) > MAX_CHUNK_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "Fenêtre audio trop lourde : le navigateur doit encoder en "
                "Opus mono 16 kHz.",
            )

        path = config.chunk_dir / f"job{job_id}_chunk{index}{CHUNK_SUFFIX}"
        path.write_bytes(body)
        db.set_chunk_status(job_id, index, "en_cours", error=None)
        db.set_job_status(job_id, "en_cours")

        # 202 tout de suite : Cloudflare coupe vers 100 s, la
        # transcription dure souvent plus longtemps.
        task = asyncio.create_task(_run_chunk(job, window, path))
        app.state.tasks.add(task)
        task.add_done_callback(app.state.tasks.discard)
        return {"accepted": True, "index": index, "bytes": len(body)}

    @app.get("/api/jobs/{job_id}")
    def job_state(job_id: int, owner_id: int = Depends(current_user)) -> dict:
        job = owned_job(job_id, owner_id)
        chunks = db.chunks_for_job(job_id)
        return {
            "job_id": job_id,
            "status": job["status"],
            "error": job["error_message"],
            "filename": job["filename"],
            "model": job["model"],
            "title": job["title"],
            "cost_usd": job["cloud_cost_usd"],
            "chunks": [
                {
                    "index": c["idx"],
                    "start": c["start_second"],
                    "end": c["end_second"],
                    "status": c["status"],
                    "error": c["error"],
                }
                for c in chunks
            ],
            # Ce que le navigateur doit (ré)encoder : la reprise après
            # onglet fermé ou réseau coupé tient dans cette liste.
            "missing_chunks": [
                c["idx"] for c in chunks if c["status"] not in {"termine"}
            ],
        }

    @app.post("/api/jobs/{job_id}/finalize", response_model=FinalizeResponse)
    def finalize(job_id: int, owner_id: int = Depends(current_user)) -> FinalizeResponse:
        job = owned_job(job_id, owner_id)
        chunks = db.chunks_for_job(job_id)
        missing = [c["idx"] for c in chunks if c["status"] != "termine"]
        if missing:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Fenêtres encore manquantes : " + ", ".join(str(i) for i in missing),
            )

        results = [
            CloudChunkResult.from_dict(json.loads(c["result_json"] or "{}"))
            for c in chunks
        ]
        merged = merge_chunk_results(results)
        text = transcript_text(merged.segments)
        # Relancer une réunion pour rattraper une fenêtre ne doit pas
        # détruire la version déjà relue.
        db.archive_current_version(job_id)
        db.replace_segments(job_id, merged.segments)
        db.finish_job(
            job_id,
            title=merged.title,
            transcript=text,
            speakers=merged.speakers,
            technical_terms=merged.technical_terms,
            cost_usd=merged.usage.cost_usd,
        )
        for c in chunks:
            _discard(config.chunk_dir / f"job{job_id}_chunk{c['idx']}{CHUNK_SUFFIX}")
        return FinalizeResponse(
            job_id=job_id,
            title=merged.title,
            transcript=text,
            speakers=merged.speakers,
            technical_terms=merged.technical_terms,
            cost_usd=merged.usage.cost_usd,
        )

    # -- bibliothèque --------------------------------------------------

    @app.get("/api/jobs")
    def list_jobs(owner_id: int = Depends(current_user)) -> list[dict]:
        return [
            {
                "job_id": job["id"],
                "filename": job["filename"],
                "title": job["title"],
                "status": job["status"],
                "model": job["model"],
                "duration_seconds": job["duration_seconds"],
                "cost_usd": job["cloud_cost_usd"],
                "created_at": job["created_at"],
                "has_versions": bool(job["previous_versions_json"]),
            }
            for job in db.list_jobs(owner_id)
        ]

    @app.get("/api/jobs/{job_id}/detail")
    def job_detail(job_id: int, owner_id: int = Depends(current_user)) -> dict:
        job = owned_job(job_id, owner_id)
        return {
            "job_id": job_id,
            "filename": job["filename"],
            "title": job["title"],
            "status": job["status"],
            "model": job["model"],
            "duration_seconds": job["duration_seconds"],
            "cost_usd": job["cloud_cost_usd"],
            "transcript": job["transcript"] or "",
            "speakers": json.loads(job["speaker_map_json"] or "{}"),
            "technical_terms": json.loads(job["technical_terms_json"] or "[]"),
            "segments": db.segments_for_job(job_id),
            "previous_versions": json.loads(job["previous_versions_json"] or "[]"),
        }

    @app.patch("/api/jobs/{job_id}")
    def patch_context(
        job_id: int, patch: ContextPatch, owner_id: int = Depends(current_user)
    ) -> dict:
        owned_job(job_id, owner_id)
        db.update_job_context(
            job_id,
            title=patch.title,
            speakers=patch.speakers,
            technical_terms=patch.technical_terms,
        )
        return {"updated": True}

    @app.post("/api/jobs/{job_id}/terms/replace")
    def replace_term_route(
        job_id: int, payload: TermReplacement, owner_id: int = Depends(current_user)
    ) -> dict:
        job = owned_job(job_id, owner_id)
        transcript, segments, terms, occurrences = replace_term(
            transcript=job["transcript"] or "",
            segments=db.segments_for_job(job_id),
            technical_terms=json.loads(job["technical_terms_json"] or "[]"),
            old=payload.old,
            new=payload.new,
        )
        if occurrences:
            db.set_transcript(job_id, transcript)
            # `segments_for_job` renvoie des colonnes SQL ; `replace_segments`
            # attend le vocabulaire des segments cloud.
            db.replace_segments(
                job_id,
                [
                    {
                        "start": s["start_second"],
                        "end": s["end_second"],
                        "speaker": s["speaker"],
                        "text": s["text"],
                    }
                    for s in segments
                ],
            )
        db.update_job_context(job_id, technical_terms=terms)
        return {"occurrences": occurrences, "technical_terms": terms}

    @app.post("/api/jobs/{job_id}/chunks/{index}/reset", status_code=status.HTTP_200_OK)
    def reset_chunk(
        job_id: int, index: int, owner_id: int = Depends(current_user)
    ) -> dict:
        job = owned_job(job_id, owner_id)
        if index < 0 or index >= int(job["chunk_count"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Fenêtre inconnue.")
        db.reset_chunk(job_id, index)
        # Le job repart en attente : `missing_chunks` guidera le navigateur
        # vers cette seule fenêtre, sans repayer les autres.
        db.set_job_status(job_id, "en_attente")
        return {"reset": index}

    @app.get("/api/search")
    def search(q: str = "", owner_id: int = Depends(current_user)) -> list[dict]:
        return db.search_segments(owner_id, q)

    # -- tâche de fond -------------------------------------------------

    async def _run_chunk(job: dict, window: dict, path: Path) -> None:
        job_id = int(job["id"])
        index = int(window["idx"])
        async with app.state.semaphore:
            try:
                result = await asyncio.to_thread(_transcribe_blocking, job, window, path)
            except (CloudTranscriptionError, SecretError) as exc:
                log.warning("job %s fenêtre %s en échec : %s", job_id, index, exc)
                db.set_chunk_status(job_id, index, "erreur", error=str(exc))
                db.set_job_status(job_id, "erreur", error=str(exc))
                return
            except Exception as exc:  # garde-fou : une tâche de fond ne doit rien avaler
                log.exception("job %s fenêtre %s : erreur inattendue", job_id, index)
                db.set_chunk_status(job_id, index, "erreur", error=str(exc))
                db.set_job_status(job_id, "erreur", error=str(exc))
                return
            finally:
                _discard(path)

            db.set_chunk_status(job_id, index, "termine", error=None, result=result.to_dict())
            db.add_api_usage(
                job_id=job_id,
                provider=provider_for_model(str(job["model"])),
                model=str(job["model"]),
                step="cloud_transcription",
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_usd=result.usage.cost_usd,
            )
            remaining = [
                c for c in db.chunks_for_job(job_id) if c["status"] != "termine"
            ]
            if not remaining:
                db.set_job_status(job_id, "a_finaliser")

    def _transcribe_blocking(job: dict, window: dict, path: Path) -> CloudChunkResult:
        context = context_for_chunk(
            chunk_index=int(window["idx"]),
            chunk_count=int(job["chunk_count"]),
            start=float(window["start_second"]),
            end=float(window["end_second"]),
            language=str(job["language"]),
            context=json.loads(job["context_json"] or "{}"),
        )
        return transcribe_chunk(
            str(path),
            model_id=str(job["model"]),
            context=context,
            api_key=keys.get(),
        )

    # Monté en dernier pour ne pas masquer les routes ci-dessus. Le client
    # est servi par le même conteneur : une seule application Cloudflare
    # Access protège l'ensemble.
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir), name="static")
    return app


def _discard(path: Path) -> None:
    """Le disque du VPS est tendu : une fenêtre ne survit pas à son usage."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.warning("fenêtre %s non supprimée : %s", path, exc)


# uvicorn monte l'application par la fabrique — « uvicorn app.main:create_app
# --factory » — pour qu'importer ce module (dans les tests, par exemple) ne
# déclenche ni lecture d'environnement ni ouverture de base.
