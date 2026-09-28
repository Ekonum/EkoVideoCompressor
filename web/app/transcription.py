"""Transcription d'une fenêtre, côté serveur.

C'est le pendant serveur de la boucle de ``pipeline.py`` : tout ce qui
touchait au média (ffmpeg, découpage physique) est parti dans le
navigateur, le reste est repris tel quel. La politique de reprise vaut
d'être conservée — les 503 de Gemini sont une réalité quotidienne, pas
une hypothèse.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from cloud_transcription import (
    CloudChunkResult,
    CloudPromptContext,
    CloudTranscriptionError,
    get_cloud_provider,
    provider_for_model,
)

log = logging.getLogger("ekovideo.web")

# Mêmes paliers que le moteur macOS : court, puis on laisse respirer.
RETRY_BACKOFF_SECONDS = (5, 15, 30)


def context_for_chunk(
    *,
    chunk_index: int,
    chunk_count: int,
    start: float,
    end: float,
    language: str,
    context: dict[str, Any],
    previous_tail: str = "",
) -> CloudPromptContext:
    """Assemble le contexte d'une fenêtre à partir du job stocké."""
    return CloudPromptContext(
        language=language or "fr",
        glossary_terms=list(context.get("glossary_terms") or []),
        expected_speaker_names=list(context.get("expected_speaker_names") or []),
        meeting_context=str(context.get("meeting_context") or ""),
        odoo_context=str(context.get("odoo_context") or ""),
        known_speakers=dict(context.get("known_speakers") or {}),
        client_company=str(context.get("client_company") or ""),
        expected_min_speakers=int(context.get("expected_min_speakers") or 0),
        expected_max_speakers=int(context.get("expected_max_speakers") or 0),
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        chunk_offset_seconds=float(start),
        chunk_duration_seconds=max(float(end) - float(start), 0.0),
        previous_tail=previous_tail,
    )


def transcribe_chunk(
    audio_path: str,
    *,
    model_id: str,
    context: CloudPromptContext,
    api_key: str,
    sleeper=time.sleep,
) -> CloudChunkResult:
    """Transcrit une fenêtre, en réessayant ce qui mérite de l'être.

    Les erreurs marquées ``retryable`` par ``cloud_transcription`` (503,
    réseau, réponse tronquée) repartent après un palier ; les autres
    (clé refusée, quota) remontent immédiatement — insister ne les
    guérirait pas et coûterait du temps à l'utilisateur.
    """
    provider = get_cloud_provider(provider_for_model(model_id), api_key)
    last: CloudTranscriptionError | None = None

    for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
        try:
            return provider.transcribe(audio_path, model_id=model_id, context=context)
        except CloudTranscriptionError as exc:
            last = exc
            if not getattr(exc, "retryable", False):
                raise
            if attempt >= len(RETRY_BACKOFF_SECONDS):
                break
            delay = RETRY_BACKOFF_SECONDS[attempt]
            log.warning(
                "fenêtre %s : %s — nouvelle tentative dans %ss",
                context.chunk_index,
                exc,
                delay,
            )
            sleeper(delay)

    assert last is not None
    raise last


def transcript_text(segments: list[dict[str, Any]]) -> str:
    """Rendu texte du transcript, au même format que l'app macOS."""
    lines: list[str] = []
    for segment in segments:
        speaker = str(segment.get("speaker") or "").strip()
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{speaker} : {text}" if speaker else text)
    return "\n".join(lines)
