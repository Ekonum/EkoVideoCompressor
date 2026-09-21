"""Sonde d'identification : de quoi parle cet enregistrement ?

Une fenêtre courte, un modèle bon marché, et une seule question : qui
parle, de quelle société, à quel sujet. Pas de transcription — le texte
intégral coûte cent fois plus cher et n'apprend rien de plus pour
retrouver le dossier Odoo correspondant.

Ces indices servent ensuite à proposer un enregistrement (`crm.lead` le
plus souvent), et c'est ce dossier qui fournira le contexte de la vraie
transcription. Se tromper ici ne coûte qu'une proposition refusée.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from cloud_transcription import (
    CloudTranscriptionError,
    CloudUsage,
    GeminiClient,
    canonical_cloud_model_id,
    compute_cost_usd,
    provider_for_model,
)

# Modèle par défaut : le moins cher du catalogue. La sonde tourne sur
# chaque enregistrement déposé, donc son coût doit rester une poussière
# devant celui de la transcription.
MODELE_SONDE = "gemini-3.1-flash-lite"

# 5 minutes : assez pour les présentations du début, assez court pour
# que la sonde reste négligeable.
FENETRE_SECONDES = 300.0

SCHEMA = {
    "type": "object",
    "properties": {
        "organisations": {"type": "array", "items": {"type": "string"}},
        "personnes": {"type": "array", "items": {"type": "string"}},
        "sujets": {"type": "array", "items": {"type": "string"}},
        "resume": {"type": "string"},
    },
    "required": ["organisations", "personnes", "sujets", "resume"],
}

PROMPT = """Tu écoutes le début d'une réunion professionnelle en {langue}.

Ne transcris rien. Réponds uniquement à ceci :

- organisations : les sociétés citées ou représentées, telles qu'elles
  sont prononcées. L'orthographe exacte compte, elle servira à chercher
  un dossier : écris « Acritec », pas « une entreprise du bâtiment ».
- personnes : les prénoms et noms des interlocuteurs entendus.
- sujets : au plus cinq mots-clés du sujet traité.
- resume : une phrase, vingt mots au plus.

Une liste vide vaut mieux qu'une invention : si personne ne se nomme,
laisse « personnes » vide."""


@dataclass(slots=True)
class Indices:
    """Ce qu'on a cru comprendre, et ce que ça a coûté."""

    organisations: list[str] = field(default_factory=list)
    personnes: list[str] = field(default_factory=list)
    sujets: list[str] = field(default_factory=list)
    resume: str = ""
    usage: CloudUsage = field(default_factory=CloudUsage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "organisations": self.organisations,
            "personnes": self.personnes,
            "sujets": self.sujets,
            "resume": self.resume,
        }

    def groupes_de_recherche(
        self, ignorer: frozenset[str] = frozenset()
    ) -> list[list[str]]:
        """Les termes à chercher dans Odoo, par ordre de fiabilité.

        Trois groupes, du plus sûr au moins sûr : les sociétés, les
        personnes, les sujets. L'appelant s'arrête au premier groupe qui
        trouve — chercher « Robin » ou « Odoo » après avoir reconnu
        « Acritec » n'ajoute que du bruit, puisque ces mots-là sont dans
        presque tous nos dossiers.
        """
        vus: set[str] = set()
        groupes: list[list[str]] = []
        for source in (self.organisations, self.personnes, self.sujets):
            groupe: list[str] = []
            for terme in source:
                nettoye = terme.strip()
                cle = nettoye.lower()
                if len(nettoye) < 2 or cle in vus or cle in ignorer:
                    continue
                vus.add(cle)
                groupe.append(nettoye)
            if groupe:
                groupes.append(groupe)
        return groupes


def _liste(valeur: Any, *, maximum: int = 10) -> list[str]:
    if not isinstance(valeur, list):
        return []
    propres: list[str] = []
    for element in valeur:
        texte = str(element or "").strip()
        if texte and texte not in propres:
            propres.append(texte)
        if len(propres) >= maximum:
            break
    return propres


def identifier(
    audio: str,
    *,
    api_key: str,
    model_id: str = MODELE_SONDE,
    langue: str = "français",
    opener: Callable[..., Any] | None = None,
) -> Indices:
    """Écoute la fenêtre et rend les indices. Lève en cas d'échec —
    l'appelant décide si la sonde est bloquante (elle ne l'est pas)."""
    client = GeminiClient(api_key, opener=opener)
    fichier: dict = {}
    try:
        fichier = client.wait_until_active(client.upload_audio(audio))
        brut = client.generate_audio_json(
            model_id=model_id,
            file_uri=str(fichier.get("uri") or ""),
            mime_type=str(fichier.get("mimeType") or "audio/mp3"),
            prompt=PROMPT.format(langue=langue),
            schema=SCHEMA,
        )
    finally:
        client.delete_file(fichier)
    return _lire(brut, model_id=model_id)


def _lire(payload: dict, *, model_id: str) -> Indices:
    candidats = payload.get("candidates") or []
    texte = ""
    for part in (candidats[0].get("content", {}).get("parts") or []) if candidats else []:
        texte += str(part.get("text") or "")
    try:
        import json

        donnees = json.loads(texte or "{}")
    except ValueError as exc:
        raise CloudTranscriptionError(
            "Réponse de la sonde illisible.", code="cloud_parse"
        ) from exc

    meta = payload.get("usageMetadata") or {}
    entree = int(meta.get("promptTokenCount") or 0)
    sortie = int(meta.get("candidatesTokenCount") or 0) + int(
        meta.get("thoughtsTokenCount") or 0
    )
    return Indices(
        organisations=_liste(donnees.get("organisations")),
        personnes=_liste(donnees.get("personnes")),
        sujets=_liste(donnees.get("sujets"), maximum=5),
        resume=str(donnees.get("resume") or "").strip(),
        usage=CloudUsage(
            model=canonical_cloud_model_id(model_id),
            input_tokens=entree,
            output_tokens=sortie,
            cost_usd=compute_cost_usd(model_id, entree, sortie),
        ),
    )


def fournisseur(model_id: str = MODELE_SONDE) -> str:
    return provider_for_model(model_id)
