"""
Voice Cameo — consented instant voice cloning of the creator's own voice.
Uses ElevenLabs IVC and reports when the connected plan does not include it.
"""
from __future__ import annotations
import os, io
from elevenlabs.client import AsyncElevenLabs
from elevenlabs import VoiceSettings
import logging

log = logging.getLogger("nolan.voice_cameo")
el = AsyncElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY") or "replay-placeholder")
MODEL = "eleven_multilingual_v2"

ENROLLMENT_TEXT = (
    "In this moment I am speaking clearly and at a natural pace. "
    "My name does not matter. What matters is the story. "
    "I am recording this so that my voice can become part of something greater — "
    "a mystery, a dream, a memory that refuses to fade. "
    "The rain falls on the platform. The phone vibrates. And somewhere, "
    "a voice that should not exist says: I remember you."
)
PREVIEW_LINE = "I see you, Maya. I am the only one who does."


class VoiceClonePlanRequired(RuntimeError):
    """The connected ElevenLabs plan does not include Instant Voice Cloning."""


async def clone_voice(audio_bytes: bytes, session_id: str) -> tuple[str | None, bool]:
    """
    Upload audio_bytes to ElevenLabs IVC.
    Returns (voice_id, requires_verification).
    Raises VoiceClonePlanRequired when the account needs an ElevenLabs upgrade.
    Returns (None, False) for other failures so the story can still use its
    selected stock voice.
    """
    try:
        # ElevenLabs 1.50 exposes instant voice cloning as ``voices.add``.
        # ``voices.ivc.create`` is not part of that SDK and made every clone
        # request fall straight into the stock-voice fallback.
        result = await el.voices.add(
            name=f"nolan-cameo-{session_id[:8]}",
            files=[io.BytesIO(audio_bytes)],
            remove_background_noise=True,
        )
        log.info("Voice Cameo created: voice_id=%s requires_verification=%s",
                 result.voice_id, result.requires_verification)
        return result.voice_id, result.requires_verification
    except Exception as exc:
        error_text = f"{exc} {getattr(exc, 'body', '')}".lower()
        if (
            "paid_plan_required" in error_text
            or "can_not_use_instant_voice_cloning" in error_text
            or "instant voice cloning" in error_text and "subscription" in error_text
        ):
            log.info("Voice Cameo cloning needs an ElevenLabs plan upgrade")
            raise VoiceClonePlanRequired from exc
        log.warning("Voice Cameo cloning failed: %s — using stock voice", exc)
        return None, False


async def preview_cameo(voice_id: str, text: str = PREVIEW_LINE) -> bytes:
    """Synthesise a short preview line with the cloned voice."""
    # The async SDK returns an async iterator directly; awaiting it raises
    # before any preview bytes are generated.
    gen = el.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=MODEL,
        voice_settings=VoiceSettings(stability=0.6, similarity_boost=0.88),
    )
    chunks = []
    async for chunk in gen:
        chunks.append(chunk)
    return b"".join(chunks)


async def delete_cameo(voice_id: str) -> bool:
    """Delete the cloned voice from ElevenLabs. Returns True on success."""
    try:
        await el.voices.delete(voice_id=voice_id)
        log.info("Voice Cameo %s deleted", voice_id)
        return True
    except Exception as exc:
        log.warning("Could not delete Voice Cameo %s: %s", voice_id, exc)
        return False
