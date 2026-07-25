"""
Audio Director Agent — converts a production script to ElevenLabs TTS audio per character.
Handles Indian English accent via eleven_multilingual_v2.
"""
from __future__ import annotations
import os, asyncio, tempfile, json, hashlib
from pathlib import Path
from elevenlabs.client import AsyncElevenLabs
from elevenlabs import VoiceSettings
from schemas import ProductionScript, ProductionLine
import logging

log = logging.getLogger("nolan.audio_director")

el = AsyncElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

VOICE_MAP: dict[str, str] = {
    "NARRATOR": os.getenv("VOICE_ID_NARRATOR", "pqHfZKP75CvOlQylNhV4"),
    "MAYA":     os.getenv("VOICE_ID_FEMALE",   "jBpfuIE2acCO8z3wKNLl"),
    "KARAN":    os.getenv("VOICE_ID_MALE",     "iP95p4xoKVk53GoZ742B"),
    "BROTHER":  os.getenv("VOICE_ID_MALE",     "iP95p4xoKVk53GoZ742B"),
}
STOCK_VOICES = [
    os.getenv("VOICE_ID_NARRATOR", "pqHfZKP75CvOlQylNhV4"),
    os.getenv("VOICE_ID_FEMALE", "jBpfuIE2acCO8z3wKNLl"),
    os.getenv("VOICE_ID_MALE", "iP95p4xoKVk53GoZ742B"),
]
MODEL = "eleven_multilingual_v2"
DEFAULT_SETTINGS = VoiceSettings(stability=0.55, similarity_boost=0.82, style=0.2)


async def synthesise_line(
    character: str,
    text: str,
    voice_note: str | None,
    cameo_voice_id: str | None,
    cameo_character: str | None,
    emotion: str | None,
) -> bytes:
    """Return MP3 bytes for one dialogue line."""
    # Use Voice Cameo if this character is the cameo
    if cameo_voice_id and cameo_character and character.upper() == cameo_character.upper():
        voice_id = cameo_voice_id
    else:
        # Unknown characters must not all collapse into the narrator voice.
        voice_id = VOICE_MAP.get(character.upper())
        if not voice_id:
            voice_id = STOCK_VOICES[int(hashlib.sha256(character.upper().encode()).hexdigest(), 16) % len(STOCK_VOICES)]

    # Adjust settings for voice notes (e.g. [whispering])
    settings = DEFAULT_SETTINGS
    delivery = f"{voice_note or ''} {emotion or ''}".lower()
    if "whisper" in delivery:
        settings = VoiceSettings(stability=0.75, similarity_boost=0.9, style=0.0)
    elif any(word in delivery for word in ("afraid", "alarmed", "panic", "urgent", "angry", "defiant")):
        settings = VoiceSettings(stability=0.32, similarity_boost=0.8, style=0.65)
    elif any(word in delivery for word in ("sad", "grief", "quiet", "tender", "emotional")):
        settings = VoiceSettings(stability=0.48, similarity_boost=0.86, style=0.45)

    # The ElevenLabs async SDK returns an async generator directly. Awaiting it
    # raises before a single byte is generated.
    audio_gen = el.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id=MODEL,
        voice_settings=settings,
    )
    # elevenlabs SDK returns a generator; collect bytes
    chunks = []
    async for chunk in audio_gen:
        chunks.append(chunk)
    return b"".join(chunks)


async def generate_voice_lines(
    script: ProductionScript,
    cameo_voice_id: str | None,
    cameo_character: str | None,
    emit_token,
    out_dir: Path,
) -> list[dict]:
    """
    Synthesise every dialogue line in the production script.
    Returns list of {type, path, duration, character, ...} for mixer.
    """
    await emit_token("\n[Audio Director] Synthesising character voices...\n")
    timeline: list[dict] = []

    tasks = []
    for i, line in enumerate(script.lines):
        if line.type == "dialogue" and line.text and line.character:
            tasks.append((i, line))

    # The hackathon ElevenLabs plan allows only two concurrent generations.
    # One-at-a-time is a little slower but keeps the cinematic payoff reliable.
    sem = asyncio.Semaphore(1)

    async def synthesise_with_sem(idx: int, line: ProductionLine):
        async with sem:
            await emit_token(f"  ► {line.character}: {line.text[:50]}...\n")
            for attempt in range(3):
                try:
                    audio_bytes = await synthesise_line(
                        line.character, line.text,
                        line.voice_note, cameo_voice_id, cameo_character, line.emotion,
                    )
                    break
                except Exception as exc:
                    if attempt == 2 or ("429" not in str(exc) and "concurrent_limit" not in str(exc)):
                        raise
                    await emit_token("    waiting briefly for the voice studio...\n")
                    await asyncio.sleep(attempt + 1)
            path = out_dir / f"line_{idx:03d}_{line.character}.mp3"
            path.write_bytes(audio_bytes)
            return idx, str(path)

    results = await asyncio.gather(*[synthesise_with_sem(i, l) for i, l in tasks])
    path_map = dict(results)

    for i, line in enumerate(script.lines):
        entry: dict = {"type": line.type, "index": i}
        if line.type == "dialogue":
            entry["path"] = path_map.get(i)
            entry["character"] = line.character
            entry["pause_after"] = 0.4
        elif line.type == "silence":
            entry["duration"] = line.duration_seconds or 1.0
        elif line.type in ("ambience", "sfx", "music"):
            entry["description"] = line.description
            entry["duration"] = line.duration_seconds or 2.0
        timeline.append(entry)

    await emit_token(f"\n[Audio Director] {len(tasks)} lines synthesised.\n")
    return timeline
