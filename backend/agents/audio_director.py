"""
Audio Director Agent — renders dialogue and sound-design stems for the mixer.
Handles multilingual dialogue via ElevenLabs and generated SFX for cinematic cues.
"""
from __future__ import annotations
import os, asyncio, re, time
from pathlib import Path
from elevenlabs.client import AsyncElevenLabs
from elevenlabs import VoiceSettings
from openai import AsyncOpenAI
from schemas import ProductionScript, ProductionLine
import logging

log = logging.getLogger("nolan.audio_director")

el = AsyncElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY") or "replay-placeholder")
# ElevenLabs remains the primary voice studio.  OpenAI TTS is intentionally a
# per-line fallback: a temporary voice entitlement or provider issue should not
# discard a completed episode.
oai_tts = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY") or "replay-placeholder", max_retries=0, timeout=45.0)

VOICE_MAP: dict[str, str] = {
    "NARRATOR": os.getenv("VOICE_ID_NARRATOR", "pqHfZKP75CvOlQylNhV4"),
    "KARAN":    os.getenv("VOICE_ID_MALE",     "iP95p4xoKVk53GoZ742B"),
    "BROTHER":  os.getenv("VOICE_ID_MALE",     "iP95p4xoKVk53GoZ742B"),
}
PRESENTATION_VOICES = {
    # These defaults are in the account's standard premade catalogue.  The old
    # feminine default was not available to the configured ElevenLabs account,
    # so a selected feminine cast could abort the whole render.
    "feminine": os.getenv("VOICE_ID_FEMALE", "pFZP5JQG7iQjIQuC4Bku"),
    "masculine": os.getenv("VOICE_ID_MALE", "iP95p4xoKVk53GoZ742B"),
    "neutral": os.getenv("VOICE_ID_NARRATOR", "SAz9YHcvj6GT2YYXdXww"),
}
# Multilingual v2 is reliable and economical for long-form Hindi/English, but
# it does not support Telugu, Kannada, or Malayalam. Eleven v3 does, and is
# also the model with expressive delivery tags for dramatic dialogue.
STABLE_MODEL = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
EXPRESSIVE_MODEL = os.getenv("ELEVENLABS_EXPRESSIVE_TTS_MODEL", "eleven_v3")
V2_LANGUAGE_CODES = {
    "en", "ja", "zh", "de", "hi", "fr", "ko", "pt", "it", "es", "id",
    "nl", "tr", "fil", "pl", "sv", "bg", "ro", "ar", "cs", "el", "fi",
    "hr", "ms", "sk", "da", "ta", "uk", "ru",
}
DEFAULT_SETTINGS = VoiceSettings(stability=0.52, similarity_boost=0.84, style=0.28, use_speaker_boost=True)
CAST_ALIASES = {
    "female": "feminine",
    "woman": "feminine",
    "girl": "feminine",
    "male": "masculine",
    "man": "masculine",
    "boy": "masculine",
}
OPENAI_FALLBACK_VOICES = {
    "feminine": "shimmer",
    "masculine": "onyx",
    "neutral": "alloy",
}
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
VOICE_CATALOGUE_TTL_SECONDS = 300
_voice_catalogue: list[dict[str, str]] = []
_voice_catalogue_loaded_at = 0.0
LANGUAGE_CODES = {
    "english": "en",
    "eng": "en",
    "hindi": "hi",
    "hin": "hi",
    "telugu": "te",
    "tel": "te",
    "tamil": "ta",
    "tam": "ta",
    "kannada": "kn",
    "kan": "kn",
    "malayalam": "ml",
    "mal": "ml",
}
LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "te": "Telugu",
    "ta": "Tamil",
    "kn": "Kannada",
    "ml": "Malayalam",
}


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return (stem or "audio")[:48]


def _language_code(value: str | None) -> str | None:
    """Turn a creator preference into the ISO code accepted by ElevenLabs."""
    if not value or value.strip().lower() == "auto":
        return None
    normalized = value.strip().lower().replace("_", "-")
    normalized = LANGUAGE_CODES.get(normalized, normalized)
    # Accept normal BCP-47 preferences such as hi-IN without sending a locale
    # where the speech provider expects the base language code.
    return normalized.split("-", 1)[0]


def _language_direction(language_code: str | None) -> str:
    if language_code:
        language = LANGUAGE_NAMES.get(language_code, language_code)
        return f"Speak the supplied text naturally in {language}; preserve its words and do not translate it."
    return "Speak in the language of the supplied dialogue; preserve its words and do not translate it."


def _model_for_dialogue(text: str, language: str | None) -> tuple[str, str | None]:
    """Pick v3 whenever the script needs a language v2 cannot speak."""
    language_code = _language_code(language)
    # Auto-detection can be absent for typed stories. Telugu/Kannada/Malayalam
    # Unicode makes the required model unambiguous without another API call.
    uses_v3_script = bool(re.search(r"[\u0C00-\u0D7F]", text))
    if language_code and language_code not in V2_LANGUAGE_CODES or uses_v3_script:
        return EXPRESSIVE_MODEL, language_code
    return STABLE_MODEL, language_code


def _performance_text(text: str, voice_note: str | None, emotion: str | None, model_id: str) -> str:
    """Give v3 a non-spoken delivery cue while leaving stable v2 text untouched."""
    if model_id != EXPRESSIVE_MODEL:
        return text
    delivery = ", ".join(part.strip(" []") for part in (voice_note, emotion) if part and part.strip())
    if not delivery:
        return text
    # Audio tags are direction, not script. Keep them short and single-line so
    # a user-provided note cannot turn into an arbitrary control payload.
    clean = re.sub(r"[\[\]\r\n]+", " ", delivery)
    clean = re.sub(r"\s+", " ", clean).strip()[:120]
    return f"[{clean}] {text}" if clean else text


def _cast_value(character: str, voice_cast: dict[str, str]) -> str | None:
    return voice_cast.get(character.upper()) or voice_cast.get(character)


def _selected_voice_id(character: str, voice_cast: dict[str, str]) -> str | None:
    value = _cast_value(character, voice_cast)
    if not value or not value.lower().startswith("voice:"):
        return None
    voice_id = value.split(":", 1)[1].strip()
    return voice_id or None


def _selected_presentation(character: str, voice_cast: dict[str, str]) -> str | None:
    value = _cast_value(character, voice_cast)
    if not value:
        return None
    if value.lower().startswith("voice:"):
        return None
    if value.lower().startswith("auto:"):
        value = value.split(":", 1)[1]
    return CAST_ALIASES.get(value.lower(), value.lower())


def _voice_for(character: str, cameo_voice_id: str | None, cameo_character: str | None, voice_cast: dict[str, str]) -> str:
    if cameo_voice_id and cameo_character and character.upper() == cameo_character.upper():
        return cameo_voice_id

    # A creator's exact voice choice must win over auto presentation and legacy
    # character-name defaults.
    selected_voice = _selected_voice_id(character, voice_cast)
    if selected_voice:
        return selected_voice
    presentation = _selected_presentation(character, voice_cast)
    if presentation:
        return PRESENTATION_VOICES.get(presentation, PRESENTATION_VOICES["neutral"])

    # The UI defaults its narrator choice to neutral. Do not silently route an
    # untouched narrator through the old masculine narrator ID.
    if character.upper() == "NARRATOR":
        return PRESENTATION_VOICES["neutral"]
    return VOICE_MAP.get(character.upper()) or PRESENTATION_VOICES["neutral"]


def _presentation_for(
    character: str,
    voice_cast: dict[str, str],
    available_voices: dict[str, dict[str, str]] | None = None,
) -> str:
    """Return the intended presentation even when the cast was left on auto."""
    selected_voice = _selected_voice_id(character, voice_cast)
    if selected_voice and available_voices:
        gender = available_voices.get(selected_voice, {}).get("gender")
        if gender == "female":
            return "feminine"
        if gender == "male":
            return "masculine"
    explicit = _selected_presentation(character, voice_cast)
    if explicit in PRESENTATION_VOICES:
        return explicit
    legacy_voice = VOICE_MAP.get(character.upper())
    if legacy_voice and legacy_voice == PRESENTATION_VOICES["masculine"]:
        return "masculine"
    return "neutral"


async def list_account_voices() -> list[dict[str, str]]:
    """Return selectable voices from the configured ElevenLabs account."""
    global _voice_catalogue, _voice_catalogue_loaded_at
    if _voice_catalogue and time.monotonic() - _voice_catalogue_loaded_at < VOICE_CATALOGUE_TTL_SECONDS:
        return [dict(voice) for voice in _voice_catalogue]
    try:
        response = await el.voices.get_all()
        catalogue: list[dict[str, str]] = []
        for voice in getattr(response, "voices", []) or []:
            voice_id = getattr(voice, "voice_id", None)
            if not voice_id:
                continue
            labels = getattr(voice, "labels", {}) or {}
            catalogue.append({
                "voice_id": str(voice_id),
                "name": str(getattr(voice, "name", "stock voice")),
                "gender": str(labels.get("gender", "")).lower(),
                "category": str(getattr(voice, "category", "")),
            })
        _voice_catalogue = catalogue
        _voice_catalogue_loaded_at = time.monotonic()
        return [dict(voice) for voice in catalogue]
    except Exception as exc:
        raise RuntimeError("Could not load the ElevenLabs voice catalogue") from exc


async def _available_account_voices() -> dict[str, dict[str, str]]:
    """Read the current account catalogue without making rendering depend on it."""
    try:
        catalogue = await list_account_voices()
        return {voice["voice_id"]: voice for voice in catalogue}
    except Exception as exc:
        # A catalogue lookup is a helpful preflight check, never a new failure
        # point. The normal ElevenLabs/OpenAI render fallback still applies.
        log.warning("Could not read ElevenLabs voice catalogue: %s", exc)
        return {}


async def _resolved_voice_id(
    character: str,
    cameo_voice_id: str | None,
    cameo_character: str | None,
    voice_cast: dict[str, str],
    available_voices: dict[str, dict[str, str]] | None,
) -> tuple[str, str | None]:
    """Use the selected voice when it is available, otherwise a same-style stock voice."""
    requested = _voice_for(character, cameo_voice_id, cameo_character, voice_cast)
    if cameo_voice_id and cameo_character and character.upper() == cameo_character.upper():
        return requested, None
    if not available_voices or requested in available_voices:
        return requested, None

    # Exact creator choices must not be replaced with a different stock voice.
    # If a previously saved voice is no longer available, the provider fallback
    # below is more honest than silently changing that cast.
    if _selected_voice_id(character, voice_cast):
        return requested, None

    presentation = _presentation_for(character, voice_cast, available_voices)
    gender = {"feminine": "female", "masculine": "male", "neutral": "neutral"}[presentation]
    candidates = [
        (voice_id, details) for voice_id, details in available_voices.items()
        if details.get("gender") == gender
    ]
    # An account can have a limited catalogue. Keeping the episode audible is
    # more useful than rejecting a creator's whole render in that case.
    if not candidates:
        candidates = list(available_voices.items())
    if not candidates:
        return requested, None
    replacement_id, replacement = candidates[0]
    return replacement_id, (
        f"{character}'s requested {presentation} stock voice was unavailable; "
        f"casting {replacement.get('name', 'an available stock voice')} for this take."
    )


def _settings_for_delivery(voice_note: str | None, emotion: str | None) -> VoiceSettings:
    delivery = f"{voice_note or ''} {emotion or ''}".lower()
    if "whisper" in delivery or "hushed" in delivery:
        return VoiceSettings(stability=0.68, similarity_boost=0.88, style=0.18, use_speaker_boost=True)
    if any(word in delivery for word in ("cry", "sob", "weeping", "breaking", "grief", "devastat", "heartbreak")):
        return VoiceSettings(stability=0.24, similarity_boost=0.78, style=0.92, use_speaker_boost=True)
    if any(word in delivery for word in ("afraid", "alarmed", "panic", "urgent", "angry", "rage", "defiant", "terrified")):
        return VoiceSettings(stability=0.30, similarity_boost=0.80, style=0.78, use_speaker_boost=True)
    if any(word in delivery for word in ("sad", "quiet", "tender", "emotional", "numb", "soft")):
        return VoiceSettings(stability=0.44, similarity_boost=0.84, style=0.58, use_speaker_boost=True)
    if any(word in delivery for word in ("distorted", "cold", "threatening", "flat")):
        return VoiceSettings(stability=0.38, similarity_boost=0.76, style=0.68, use_speaker_boost=True)
    return DEFAULT_SETTINGS


def _sfx_prompt(description: str, kind: str) -> str:
    desc = (description or kind or "cinematic sound").strip()
    lower = desc.lower()
    if kind == "ambience":
        return f"Seamless cinematic background ambience: {desc}. Natural room tone, no dialogue, no music."
    if kind == "music":
        return f"Subtle cinematic underscore: {desc}. Low volume tension bed, no vocals, no dialogue."
    if any(word in lower for word in ("cry", "sob", "weeping", "wail")):
        return f"Nonverbal human crying sound effect: {desc}. Emotional sobs and breath breaks, no spoken words."
    return f"Cinematic sound effect: {desc}. Realistic, close perspective, no spoken words."


async def synthesise_line(
    character: str,
    text: str,
    voice_note: str | None,
    cameo_voice_id: str | None,
    cameo_character: str | None,
    emotion: str | None,
    voice_cast: dict[str, str],
    available_voices: dict[str, dict[str, str]] | None = None,
    language: str | None = None,
) -> tuple[bytes, str | None]:
    """Return MP3 bytes for one dialogue line."""
    presentation = _presentation_for(character, voice_cast, available_voices)
    voice_id, cast_note = await _resolved_voice_id(
        character, cameo_voice_id, cameo_character, voice_cast, available_voices,
    )
    settings = _settings_for_delivery(voice_note, emotion)
    model_id, language_code = _model_for_dialogue(text, language)
    spoken_text = _performance_text(text, voice_note, emotion, model_id)

    # The ElevenLabs async SDK returns an async generator directly. Awaiting it
    # raises before a single byte is generated.
    async def collect(selected_voice: str) -> bytes:
        kwargs = dict(
            voice_id=selected_voice, text=spoken_text, model_id=model_id, voice_settings=settings,
        )
        # ElevenLabs documents language_code as unsupported for Multilingual
        # v2. It is useful on v3 for short or ambiguous Telugu/Hindi lines.
        if language_code and model_id != STABLE_MODEL:
            kwargs["language_code"] = language_code
        audio_gen = el.text_to_speech.convert(**kwargs)
        chunks = []
        async for chunk in audio_gen:
            chunks.append(chunk)
        return b"".join(chunks)

    try:
        return await collect(voice_id), cast_note
    except Exception as exc:
        # The audio endpoint supports instructions, but the project keeps an
        # older SDK that does not yet expose that keyword. extra_body preserves
        # the supported request shape until the dependency is upgraded.
        delivery = "; ".join(part for part in (voice_note, emotion) if part) or "natural and clear"
        instructions = (
            f"Speak only the supplied dialogue as {character}. "
            f"Delivery: {delivery}. {_language_direction(language_code)} Keep the emotion believable, with no narration, "
            "no added words, and no sound effects."
        )
        try:
            fallback = await oai_tts.audio.speech.create(
                model=OPENAI_TTS_MODEL,
                voice=OPENAI_FALLBACK_VOICES[presentation],
                input=text,
                response_format="mp3",
                extra_body={"instructions": instructions},
            )
            log.warning("ElevenLabs line failed for %s; used OpenAI speech fallback: %s", character, exc)
            note = "ElevenLabs was unavailable for this line; an emotional OpenAI speech take was used instead."
            return fallback.content, f"{cast_note} {note}".strip() if cast_note else note
        except Exception as fallback_exc:
            raise RuntimeError(
                f"Could not render {character}'s dialogue with either voice provider. "
                "Please try the audio render once more."
            ) from fallback_exc


async def synthesise_sound_effect(description: str, duration_seconds: float, kind: str) -> bytes:
    """Return MP3 bytes for ambience, SFX, or music using ElevenLabs SFX."""
    duration = min(22.0, max(0.5, float(duration_seconds or 1.0)))
    audio_gen = el.text_to_sound_effects.convert(
        text=_sfx_prompt(description, kind),
        duration_seconds=duration,
        prompt_influence=0.62,
        request_options={"timeout_in_seconds": 35, "chunk_size": 4096},
    )
    chunks = []
    async for chunk in audio_gen:
        chunks.append(chunk)
    return b"".join(chunks)


async def generate_voice_lines(
    script: ProductionScript,
    cameo_voice_id: str | None,
    cameo_character: str | None,
    voice_cast: dict[str, str],
    emit_token,
    out_dir: Path,
    language: str | None = None,
) -> list[dict]:
    """
    Synthesise every dialogue line in the production script.
    Returns list of {type, path, duration, character, ...} for mixer.
    """
    await emit_token("\n[Audio Director] Synthesising character voices...\n")
    timeline: list[dict] = []
    available_voices = await _available_account_voices()

    dialogue_tasks = []
    sound_tasks = []
    for i, line in enumerate(script.lines):
        if line.type == "dialogue" and line.text and line.character:
            dialogue_tasks.append((i, line))
        elif line.type in ("ambience", "sfx", "music") and line.description:
            sound_tasks.append((i, line))

    # The hackathon ElevenLabs plan allows only two concurrent generations.
    # One-at-a-time is a little slower but keeps the cinematic payoff reliable.
    sem = asyncio.Semaphore(1)

    async def synthesise_dialogue_with_sem(idx: int, line: ProductionLine):
        async with sem:
            await emit_token(f"  ► {line.character}: {line.text[:50]}...\n")
            for attempt in range(3):
                try:
                    audio_bytes, cast_note = await synthesise_line(
                        line.character, line.text,
                        line.voice_note, cameo_voice_id, cameo_character, line.emotion,
                        voice_cast, available_voices, language,
                    )
                    if cast_note:
                        await emit_token(f"    {cast_note}\n")
                    break
                except Exception as exc:
                    if attempt == 2 or ("429" not in str(exc) and "concurrent_limit" not in str(exc)):
                        raise
                    await emit_token("    waiting briefly for the voice studio...\n")
                    await asyncio.sleep(attempt + 1)
            path = out_dir / f"line_{idx:03d}_{_safe_stem(line.character or 'dialogue')}.mp3"
            path.write_bytes(audio_bytes)
            return idx, str(path)

    async def synthesise_sound_with_sem(idx: int, line: ProductionLine):
        async with sem:
            await emit_token(f"  ◇ {line.type}: {(line.description or '')[:64]}...\n")
            try:
                audio_bytes = await synthesise_sound_effect(
                    line.description or line.type,
                    line.duration_seconds or (6.0 if line.type == "ambience" else 2.0),
                    line.type,
                )
            except Exception as exc:
                log.warning("Sound generation failed for %s '%s': %s", line.type, line.description, exc)
                return idx, None
            path = out_dir / f"{line.type}_{idx:03d}_{_safe_stem(line.description or line.type)}.mp3"
            path.write_bytes(audio_bytes)
            return idx, str(path)

    dialogue_results = await asyncio.gather(*[synthesise_dialogue_with_sem(i, l) for i, l in dialogue_tasks])
    sound_results = await asyncio.gather(*[synthesise_sound_with_sem(i, l) for i, l in sound_tasks])
    path_map = dict(dialogue_results)
    sound_path_map = {idx: path for idx, path in sound_results if path}

    for i, line in enumerate(script.lines):
        entry: dict = {"type": line.type, "index": i}
        if line.type == "dialogue":
            entry["path"] = path_map.get(i)
            entry["character"] = line.character
            entry["emotion"] = line.emotion
            entry["voice_note"] = line.voice_note
            entry["pause_after"] = 0.4
        elif line.type == "silence":
            entry["duration"] = line.duration_seconds or 1.0
        elif line.type in ("ambience", "sfx", "music"):
            entry["description"] = line.description
            entry["duration"] = line.duration_seconds or 2.0
            entry["path"] = sound_path_map.get(i)
        timeline.append(entry)

    await emit_token(f"\n[Audio Director] {len(dialogue_tasks)} dialogue lines and {len(sound_path_map)} sound-design cues rendered.\n")
    return timeline
