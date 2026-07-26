"""
Workflow — deterministic state machine that orchestrates all agents.
Each stage streams tokens via SSE queue, has a hard timeout + circuit breaker fallback.
"""
from __future__ import annotations
import asyncio, json, os, uuid
from pathlib import Path
from typing import Callable, Awaitable
from openai import AsyncOpenAI
from schemas import (
    Session, WorkflowStatus, CreativeDNA, VisionCard, StoryCharacter,
    VisionSelection, ProductionLine, ProductionScript, ConstitutionReport,
    CreativeLockDiff, ChangeRequest, EpisodeFeedback, EpisodeOutline,
    EpisodeStatus, SeriesPlan, StoryEpisode, VisualEpisodeResult,
)
from resilience import with_resilience
from fixtures import (
    FIXTURE_CONSTITUTION,
    FIXTURE_DNA,
    FIXTURE_PRODUCTION_SCRIPT,
    FIXTURE_REVISION_DIFF,
    FIXTURE_VISIONS,
)
from agents.muse import extract_dna, _fallback_dna_from_transcript
from agents.writer import (
    _dynamic_vision_fallback, _fallback_series_plan, generate_series_plan,
    generate_script, generate_visions,
)
from agents.supervisor import (
    check_constitution, analyze_change_impact, _dynamic_constitution_fallback,
    _normalize_constitution_report,
)
from agents.audio_director import generate_voice_lines
from agents.visual_director import plan_visual_episode
from agents.voice_cameo import clone_voice, preview_cameo, delete_cameo
from audio_mixer import mix_timeline
import logging

log = logging.getLogger("nolan.workflow")
oai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY") or "replay-placeholder", max_retries=0, timeout=30.0)
NOLAN_MODE = os.getenv("NOLAN_MODE", "hybrid")
SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)
TRANSCRIPTION_LANGUAGE_CODES = {
    "english": "en",
    "hindi": "hi",
    "tamil": "ta",
    "telugu": "te",
    "kannada": "kn",
    "malayalam": "ml",
}


Emitter = Callable[[str, str, object], Awaitable[None]]


# ─── Event Queue Store ────────────────────────────────────────────────────────

_queues: dict[str, asyncio.Queue] = {}

def get_queue(session_id: str) -> asyncio.Queue:
    if session_id not in _queues:
        _queues[session_id] = asyncio.Queue()
    return _queues[session_id]

async def emit(session_id: str, agent: str, event_type: str, data):
    q = get_queue(session_id)
    await q.put({"agent": agent, "type": event_type, "data": data})

async def close_stream(session_id: str):
    # The browser opens a fresh SSE subscription for each stage.  Do not leave
    # a terminal sentinel in the shared queue: it would instantly close the
    # next stage before it could receive Writer/Supervisor events.
    return None


# ─── Session persistence (in-memory + disk) ───────────────────────────────────

_sessions: dict[str, Session] = {}

def save_session(s: Session):
    _sessions[s.id] = s
    path = SESSIONS_DIR / f"{s.id}.json"
    path.write_text(s.model_dump_json())

def load_session(session_id: str) -> Session | None:
    if session_id in _sessions:
        return _sessions[session_id]
    path = SESSIONS_DIR / f"{session_id}.json"
    if path.exists():
        return Session.model_validate_json(path.read_text())
    return None

def update_status(s: Session, status: WorkflowStatus) -> Session:
    s.status = status
    save_session(s)
    return s


# ─── Workflow Stages ──────────────────────────────────────────────────────────

async def run_transcription(session_id: str, audio_bytes: bytes, language: str | None = None) -> tuple[str, str | None]:
    sid = session_id
    await emit(sid, "muse", "status", "Transcribing your idea...")

    if NOLAN_MODE == "replay":
        from fixtures import FIXTURE_TRANSCRIPT
        return FIXTURE_TRANSCRIPT, "en"

    async def live():
        import io
        file = ("idea.webm", io.BytesIO(audio_bytes), "audio/webm")
        # Omitting language enables transcription in the spoken language. A creator
        # may provide a BCP-47/ISO hint when they know it, but English is never forced.
        kwargs = {"model": "gpt-4o-transcribe", "file": file,
                  "prompt": "Transcribe faithfully in the speaker's language. Preserve names and code-switching."}
        if language and language.lower() != "auto":
            # The UI sends friendly names while the transcription API expects
            # ISO language codes. Preserve already-valid codes from API users.
            normalized_language = language.strip().lower()
            kwargs["language"] = TRANSCRIPTION_LANGUAGE_CODES.get(normalized_language, normalized_language)
        resp = await oai.audio.transcriptions.create(**kwargs)
        return resp.text, getattr(resp, "language", None)

    transcription, degraded = await with_resilience(
        stage="transcribe", provider="openai", fn=live,
        fallback_fn=lambda: ("I couldn't transcribe this recording. Please type or correct your story here.", None),
        emit_fallback=lambda msg: emit(sid, "muse", "fallback", msg),
    )
    if degraded:
        s = load_session(sid)
        if s:
            s.is_degraded = True
            s.degraded_stages.append("transcribe")
            save_session(s)
    transcript, detected_language = transcription
    await emit(sid, "muse", "artifact", {"transcript": transcript, "detected_input_language": detected_language})
    return transcript, detected_language


async def run_dna_extraction(session_id: str, transcript: str, output_language: str = "auto") -> CreativeDNA:
    sid = session_id
    await emit(sid, "muse", "status", "Extracting Creative DNA...")

    if NOLAN_MODE == "replay":
        await emit(sid, "muse", "artifact", FIXTURE_DNA.model_dump())
        return FIXTURE_DNA

    token_buf: list[str] = []
    async def emit_token(t: str):
        token_buf.append(t)
        await emit(sid, "muse", "token", t)

    async def live():
        return await extract_dna(transcript, emit_token, output_language)

    dna, degraded = await with_resilience(
        stage="dna", provider="openai", fn=live,
        fallback_fn=lambda: _fallback_dna_from_transcript(transcript),
        emit_fallback=lambda msg: emit(sid, "muse", "fallback", msg),
    )
    # Guard the user promise even when a model overlooks an explicit multi-person premise.
    if ("two strangers" in transcript.lower() or "two people" in transcript.lower()) and len(dna.characters) < 2:
        dna.characters.append(StoryCharacter(
            name="Rhea" if dna.protagonist.name != "Rhea" else "Kabir",
            role="co-protagonist", relationship_to_protagonist="stranger connected by the same event",
            want="understand why their lives overlap", secret_or_tension="their version of the truth may not match yours",
        ))
    await emit(sid, "muse", "artifact", dna.model_dump())
    return dna


async def run_vision_generation(session_id: str, dna: CreativeDNA) -> list[VisionCard]:
    sid = session_id
    await emit(sid, "writer", "status", "Auditioning three directorial visions...")

    if NOLAN_MODE == "replay":
        for v in FIXTURE_VISIONS:
            await emit(sid, "writer", "artifact", v.model_dump())
        return FIXTURE_VISIONS

    async def emit_token(t: str):
        await emit(sid, "writer", "token", t)

    async def live():
        return await generate_visions(dna, emit_token)

    visions, degraded = await with_resilience(
        stage="visions", provider="openai", fn=live,
        fallback_fn=lambda: _dynamic_vision_fallback(dna),
        emit_fallback=lambda msg: emit(sid, "writer", "fallback", msg),
    )
    for v in visions:
        await emit(sid, "writer", "artifact", v.model_dump())
    return visions


async def run_script_generation(
    session_id: str,
    dna: CreativeDNA,
    selection: VisionSelection,
    visions: list[VisionCard],
    episode_number: int = 1,
    episode_outline: EpisodeOutline | None = None,
    previous_continuity: str | None = None,
    feedback: EpisodeFeedback | None = None,
) -> ProductionScript:
    sid = session_id
    await emit(sid, "writer", "status", "Composing production script...")

    if NOLAN_MODE == "replay":
        await emit(sid, "writer", "artifact", FIXTURE_PRODUCTION_SCRIPT.model_dump())
        return FIXTURE_PRODUCTION_SCRIPT

    async def emit_token(t: str):
        await emit(sid, "writer", "token", t)

    saved_session = load_session(sid)
    selected_language = saved_session.preferences.output_language if saved_session else "auto"
    story_language = (
        selected_language
        if selected_language and selected_language.lower() != "auto"
        else (saved_session.detected_input_language if saved_session and saved_session.detected_input_language else "auto")
    ).lower().replace("_", "-")
    story_language = {
        "hindi": "hi", "telugu": "te", "tamil": "ta",
        "kannada": "kn", "malayalam": "ml", "english": "en",
    }.get(story_language, story_language)

    async def live():
        return await generate_script(
            dna, selection, visions, emit_token, story_language,
            episode_number=episode_number,
            episode_outline=episode_outline,
            previous_continuity=previous_continuity,
            feedback=feedback,
        )

    def dynamic_script_fallback() -> ProductionScript:
        name = dna.protagonist.name.upper()
        counterpart = next((c.name.upper() for c in dna.characters if c.name.lower() != dna.protagonist.name.lower()), "VOICE")
        language = story_language.split("-", 1)[0]
        if language == "hi":
            dialogue = [
                "आज हर चेहरा मुझे ऐसे देख रहा है जैसे मैं कभी यहाँ थी ही नहीं।",
                "लेकिन तुम्हारी आवाज़ ने मेरा नाम लिया। वह आवाज़ मुझे अब भी सुनाई दे रही है।",
                "अगर यह सच है, तो हमें उस जगह तक जाना होगा जहाँ से यह सब शुरू हुआ था।",
                "मैं डर रही हूँ, फिर भी इस बार मैं पीछे नहीं हटूँगी।",
            ]
            response = "मैं तुम्हें अकेला नहीं छोड़ूँगा, लेकिन जो हम खोजेंगे उसकी कीमत होगी।"
            ending = "फोन फिर बज रहा है। इस बार दूसरी तरफ़ कौन है?" if episode_number < 3 else "मैं तुम्हें याद रखूँगी। अब यह डर मेरे जीवन का फैसला नहीं करेगा।"
        elif language == "te":
            dialogue = [
                "ఈ రోజు ప్రతి ముఖం నన్ను నేను ఎప్పుడూ ఇక్కడ లేనట్టే చూస్తోంది.",
                "కానీ నీ స్వరం నా పేరు చెప్పింది. ఆ స్వరం ఇంకా నా చెవుల్లో ఉంది.",
                "ఇది నిజమైతే, ఈ అన్నీ మొదలైన చోటుకి మనం వెళ్లాలి.",
                "నాకు భయంగా ఉంది, అయినా ఈసారి నేను వెనక్కి తగ్గను.",
            ]
            response = "నేను నిన్ను ఒంటరిగా వదలను, కానీ మనం కనుగొనేది మనిద్దరినీ మార్చేస్తుంది."
            ending = "ఫోన్ మళ్లీ మోగుతోంది. ఈసారి అవతల ఎవరు ఉన్నారు?" if episode_number < 3 else "నేను నిన్ను గుర్తు పెట్టుకుంటాను. ఈ భయం ఇక నా జీవితాన్ని నిర్ణయించదు."
        else:
            dialogue = [
                f"{dna.central_conflict}. I can feel the world closing around me.",
                "But your voice said my name. That means one part of this is still real.",
                "Then we go back to the first place the signal found us, and we do not look away.",
                "I am afraid, but I am done letting fear choose for me.",
            ]
            response = "I will not leave you alone, but the truth we find may change what either of us can keep."
            ending = "The phone is ringing again. This time, who is on the other end?" if episode_number < 3 else "I choose to remember you, and I choose the life that is still mine."
        scene_title = episode_outline.title if episode_outline else f"{dna.protagonist.name}: The First Turning"
        return ProductionScript(
            title=scene_title,
            estimated_duration_seconds=90,
            lines=[
                {"type": "ambience", "description": f"A tense {dna.genre[0] if dna.genre else 'intimate drama'} atmosphere that makes the room feel unsafe", "duration_seconds": 5},
                {"type": "dialogue", "character": name, "text": dialogue[0], "emotion": dna.core_emotion, "voice_note": "close, shaken"},
                {"type": "sfx", "description": "A phone vibrates once, then stops before it can be answered", "duration_seconds": 2},
                {"type": "dialogue", "character": name, "text": dialogue[1], "emotion": "raw, disbelieving"},
                {"type": "dialogue", "character": counterpart, "text": response, "emotion": "guarded, urgent"},
                {"type": "silence", "duration_seconds": 1.4},
                {"type": "dialogue", "character": name, "text": dialogue[2], "emotion": "resolute"},
                {"type": "ambience", "description": "Wind and distant traffic rise as the choice becomes irreversible", "duration_seconds": 4},
                {"type": "dialogue", "character": counterpart, "text": dna.non_negotiables[0] if language not in {"hi", "te"} and dna.non_negotiables else "The truth is closer than either of us expected.", "emotion": "warning"},
                {"type": "dialogue", "character": name, "text": dialogue[3], "emotion": "brave, voice unsteady"},
                {"type": "sfx", "description": "The phone rings again, louder and closer than before", "duration_seconds": 2},
                {"type": "dialogue", "character": name, "text": ending, "emotion": "breathless" if episode_number < 3 else "tearful certainty"},
                {"type": "music", "description": "A restrained score holds the final emotional turn", "duration_seconds": 5},
            ],
        )

    script, _ = await with_resilience(
        stage="script", provider="openai", fn=live,
        fallback_fn=dynamic_script_fallback,
        emit_fallback=lambda msg: emit(sid, "writer", "fallback", msg),
    )
    await emit(sid, "writer", "artifact", script.model_dump())
    return script


async def run_constitution_check(
    session_id: str,
    dna: CreativeDNA,
    script: ProductionScript,
    episode_number: int = 1,
) -> ConstitutionReport:
    sid = session_id
    await emit(sid, "supervisor", "status", "Running Pocket FM Story Constitution...")

    if NOLAN_MODE == "replay":
        report = _normalize_constitution_report(FIXTURE_CONSTITUTION, script, episode_number)
        for check in report.checks:
            await emit(sid, "supervisor",
                       "violation" if not check.passed else "artifact",
                       check.model_dump())
        await emit(sid, "supervisor", "artifact", report.model_dump())
        return report

    async def emit_token(t: str):
        await emit(sid, "supervisor", "token", t)

    async def live():
        return await check_constitution(dna, script, emit_token, episode_number)

    report, _ = await with_resilience(
        stage="constitution", provider="openai", fn=live,
        fallback_fn=lambda: _dynamic_constitution_fallback(script, dna, episode_number),
        emit_fallback=lambda msg: emit(sid, "supervisor", "fallback", msg),
    )
    for check in report.checks:
        evt = "violation" if not check.passed else "artifact"
        await emit(sid, "supervisor", evt, check.model_dump())
    await emit(sid, "supervisor", "artifact", {"score": report.overall_score})
    return report


async def run_audio_render(
    session_id: str,
    script: ProductionScript,
    cameo_voice_id: str | None = None,
    cameo_character: str | None = None,
    voice_cast: dict[str, str] | None = None,
    episode_number: int | None = None,
) -> str:
    """Render final audio, keeping approved episode files separate."""
    sid = session_id
    await emit(sid, "audio_director", "status", "Creating your audio story...")

    audio_dir = SESSIONS_DIR / sid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    filename = f"episode_{episode_number:02d}.mp3" if episode_number else "pilot.mp3"
    out_path = audio_dir / filename
    public_url = f"/audio/{sid}/{filename}"

    if NOLAN_MODE == "replay":
        # Use precomputed demo audio if exists
        demo_audio = Path(__file__).parent.parent / "demo-fixtures" / "audio" / "pilot.mp3"
        if demo_audio.exists():
            import shutil
            shutil.copy(str(demo_audio), str(out_path))
            await emit(sid, "audio_director", "complete", {"url": public_url, "episode_number": episode_number})
            return public_url
        # Replay must stay fully offline. Do not fall through to a live provider
        # when the optional binary fixture was not bundled with the repository.
        await emit(sid, "audio_director", "fallback", "Replay audio fixture is unavailable; your approved script is still ready.")
        await emit(sid, "audio_director", "error", "Replay audio fixture is unavailable. Your production script is still ready.")
        return ""

    async def live():
        tts_dir = audio_dir / (f"episode_{episode_number:02d}_lines" if episode_number else "lines")
        tts_dir.mkdir(exist_ok=True)
        # A chosen output language wins. With "auto", use the language
        # detected from the creator's recording when it is available; the
        # dialogue text remains the final source of truth for mixed-language lines.
        session = load_session(sid)
        selected_language = session.preferences.output_language if session else "auto"
        audio_language = (
            selected_language
            if selected_language and selected_language.lower() != "auto"
            else (session.detected_input_language if session else None)
        )
        timeline = await generate_voice_lines(
            script, cameo_voice_id, cameo_character, voice_cast or {},
            lambda t: emit(sid, "audio_director", "token", t),
            tts_dir,
            language=audio_language,
        )
        mix_timeline(timeline, out_path)
        return public_url

    url, degraded = await with_resilience(
        stage="audio", provider="elevenlabs", fn=live,
        # Never claim an audio URL exists when ElevenLabs/mixing failed.
        fallback_fn=lambda: "",
        emit_fallback=lambda msg: emit(sid, "audio_director", "fallback", msg),
    )
    if url and out_path.exists() and out_path.stat().st_size > 0:
        await emit(sid, "audio_director", "complete", {"url": url, "episode_number": episode_number})
        return url
    await emit(sid, "audio_director", "error", "Audio could not be rendered. Your production script is still ready.")
    return ""


# ─── Three-Episode Story Workflow ────────────────────────────────────────────

def _episode(session: Session, number: int) -> StoryEpisode | None:
    return next((item for item in session.episodes if item.number == number), None)


def _continuity_summary(episode: StoryEpisode) -> str:
    """Keep continuation memory deterministic and free—no extra model call."""
    lines = episode.production_script.lines if episode.production_script else []
    last_line = next(
        (
            line.text for line in reversed(lines)
            if line.type == "dialogue" and line.text
        ),
        episode.outline.ending_promise,
    )
    return (
        f"Episode {episode.number} — {episode.outline.title}: {episode.outline.what_happens} "
        f"It ends on: {last_line}"
    )


def _sync_legacy_episode_fields(session: Session, episode: StoryEpisode) -> None:
    """Keep the original pilot routes usable while the creator uses the series flow."""
    session.active_episode_number = episode.number
    session.production_script = episode.production_script
    session.constitution_report = episode.constitution_report
    session.audio_url = episode.audio_url
    session.cover_image_url = episode.cover_image_url


def _clear_episode_media(episode: StoryEpisode) -> None:
    """Remove references that no longer match an edited or stale draft."""
    episode.audio_url = None
    episode.cover_image_url = None
    episode.actual_duration_seconds = None
    episode.continuity_summary = None
    episode.visual_episode_plan = None
    episode.visual_episode = None


async def run_series_outline(session_id: str) -> None:
    """Create the complete three-part promise without generating any costly media."""
    session = load_session(session_id)
    if not session or not session.creative_dna or not session.selected_vision or not session.visions:
        return
    sid = session_id
    await emit(sid, "writer", "status", "Planning your complete three-episode story...")
    primary = next((vision for vision in session.visions if vision.id == session.selected_vision.primary_vision_id), None)

    async def emit_token(_token: str):
        # The public studio view receives short activity messages, never the
        # writer's raw JSON plan.
        return None

    if NOLAN_MODE == "replay":
        plan = _fallback_series_plan(session.creative_dna, primary)
    else:
        plan, _ = await with_resilience(
            stage="series_outline",
            provider="openai",
            fn=lambda: generate_series_plan(
                session.creative_dna,
                primary,
                emit_token,
                session.preferences.output_language,
            ),
            fallback_fn=lambda: _fallback_series_plan(session.creative_dna, primary),
            emit_fallback=lambda message: emit(sid, "writer", "fallback", message),
        )

    session.series_plan = plan
    session.episodes = [StoryEpisode(number=outline.number, outline=outline) for outline in plan.episode_outlines]
    session.active_episode_number = 1
    # Planning is complete now. Keep the regular session state out of its
    # in-flight state so the creator can immediately choose Episode 1.
    update_status(session, WorkflowStatus.VISIONS_READY)
    await emit(sid, "writer", "artifact", {
        "series_plan": plan.model_dump(),
        "episodes": [episode.model_dump() for episode in session.episodes],
    })
    await emit(sid, "writer", "status", "Your three-episode story is ready. Choose when to draft Episode 1.")
    await emit(sid, "writer", "complete", {"status": "SERIES_OUTLINED", "episodes_count": 3})


async def run_episode_draft(session_id: str, episode_number: int) -> None:
    """Write and check one episode; never render audio before confirmation."""
    session = load_session(session_id)
    if not session or not session.creative_dna or not session.selected_vision or not session.visions:
        return
    episode = _episode(session, episode_number)
    if not episode:
        return
    previous = _episode(session, episode_number - 1) if episode_number > 1 else None
    if previous and previous.status != EpisodeStatus.APPROVED:
        await emit(session_id, "director", "error", "Approve the previous episode before drafting the next one.")
        return

    if episode.status not in {EpisodeStatus.OUTLINED, EpisodeStatus.STALE, EpisodeStatus.DRAFTING}:
        await emit(session_id, "writer", "error", "Review this episode draft before making another one.")
        return

    episode.status = EpisodeStatus.DRAFTING
    if episode.production_script:
        _clear_episode_media(episode)
    _sync_legacy_episode_fields(session, episode)
    update_status(session, WorkflowStatus.SCRIPT_DRAFTED)
    await emit(session_id, "writer", "status", f"Writer is shaping Episode {episode_number}: {episode.outline.title}.")

    script = await run_script_generation(
        session_id,
        session.creative_dna,
        session.selected_vision,
        session.visions,
        episode_number=episode_number,
        episode_outline=episode.outline,
        previous_continuity=previous.continuity_summary if previous else None,
        feedback=previous.feedback if previous else None,
    )
    report = await run_constitution_check(session_id, session.creative_dna, script, episode_number)
    episode.production_script = script
    episode.constitution_report = report
    _clear_episode_media(episode)
    episode.status = EpisodeStatus.DRAFT_READY
    _sync_legacy_episode_fields(session, episode)
    update_status(session, WorkflowStatus.CONSTITUTION_DONE)
    await emit(session_id, "writer", "artifact", {"episode": episode.model_dump()})
    await emit(session_id, "supervisor", "complete", {
        "status": "EPISODE_DRAFT_READY",
        "episode_number": episode_number,
    })


async def run_confirmed_episode_render(session_id: str, episode_number: int) -> None:
    """Spend audio credits only after the creator approves this episode draft."""
    session = load_session(session_id)
    episode = _episode(session, episode_number) if session else None
    if not session or not episode or not episode.production_script:
        return
    if episode.status not in {EpisodeStatus.DRAFT_READY, EpisodeStatus.RENDERING}:
        await emit(session_id, "audio_director", "error", "Review the episode draft before creating its audio.")
        return

    episode.status = EpisodeStatus.RENDERING
    _sync_legacy_episode_fields(session, episode)
    update_status(session, WorkflowStatus.AUDIO_RENDERING)
    cameo = session.voice_cameo
    url = await run_audio_render(
        session_id,
        episode.production_script,
        cameo.voice_id if cameo else None,
        ("NARRATOR" if cameo and cameo.assigned_to == "narrator" else cameo.character_name) if cameo else None,
        session.preferences.voice_cast,
        episode_number=episode_number,
    )
    if url:
        episode.audio_url = url
        episode.continuity_summary = _continuity_summary(episode)
        episode.status = EpisodeStatus.READY
        try:
            from audio_mixer import _decode_mp3
            rendered = _decode_mp3(SESSIONS_DIR / session_id / "audio" / f"episode_{episode_number:02d}.mp3")
            episode.actual_duration_seconds = round(len(rendered) / 1000, 1)
        except Exception:
            episode.actual_duration_seconds = float(episode.production_script.estimated_duration_seconds)
        # When the creator supplied a picture, place, or real clip, create the
        # matching edit plan from this exact approved script. This is cheap and
        # deterministic; it does not start a paid video render on its own.
        if session.visual_assets and session.creative_dna:
            try:
                plan = await plan_visual_episode(session.creative_dna, episode.production_script, session.visual_assets)
                plan.portrait_consent = any(asset.kind == "photo" and asset.consented for asset in session.visual_assets)
                plan.live_video_consent = any(asset.kind == "video" and asset.consented for asset in session.visual_assets)
                episode.visual_episode_plan = plan
                episode.visual_episode = VisualEpisodeResult(
                    status="planned",
                    message="Your uploaded media is now matched to this episode's story beats.",
                )
            except Exception as exc:
                log.warning("Visual plan failed for episode %s: %s", episode_number, exc)
        _sync_legacy_episode_fields(session, episode)
        update_status(session, WorkflowStatus.READY)
        await emit(session_id, "supervisor", "complete", {
            "status": "EPISODE_READY",
            "episode_number": episode_number,
            "audio_url": url,
        })
    else:
        episode.status = EpisodeStatus.DRAFT_READY
        _sync_legacy_episode_fields(session, episode)
        update_status(session, WorkflowStatus.CONSTITUTION_DONE)
        await emit(session_id, "supervisor", "complete", {
            "status": "EPISODE_DRAFT_READY",
            "episode_number": episode_number,
        })
    save_session(session)


async def run_continue_series(session_id: str, episode_number: int, feedback: EpisodeFeedback) -> None:
    """Lock a reviewed episode, preserve its feedback, then draft—not render—the next."""
    session = load_session(session_id)
    episode = _episode(session, episode_number) if session else None
    if not session or not episode or episode.status != EpisodeStatus.READY:
        return
    episode.feedback = feedback
    episode.continuity_summary = episode.continuity_summary or _continuity_summary(episode)
    episode.status = EpisodeStatus.APPROVED
    _sync_legacy_episode_fields(session, episode)
    save_session(session)
    await emit(session_id, "director", "status", f"Episode {episode_number} is locked. Keeping its choices for the next episode.")
    if episode_number < 3:
        await run_episode_draft(session_id, episode_number + 1)
    else:
        update_status(session, WorkflowStatus.READY)
        await emit(session_id, "director", "complete", {"status": "SERIES_COMPLETE", "episode_number": 3})


async def run_episode_revision(session_id: str, episode_number: int, feedback: EpisodeFeedback) -> None:
    """Revise the selected episode only; future unapproved drafts are safely refreshed."""
    session = load_session(session_id)
    episode = _episode(session, episode_number) if session else None
    if not session or not episode or not episode.production_script or not session.creative_dna:
        return
    if any(
        future.number > episode_number and future.status == EpisodeStatus.APPROVED
        for future in session.episodes
    ):
        await emit(
            session_id,
            "director",
            "error",
            "A later approved episode depends on this one. Revise the latest approved episode instead.",
        )
        return
    episode.feedback = feedback
    episode.status = EpisodeStatus.REVISING
    update_status(session, WorkflowStatus.REVISING)
    instruction = feedback.change_this_episode.strip()
    if not instruction:
        episode.status = EpisodeStatus.DRAFT_READY
        update_status(session, WorkflowStatus.CONSTITUTION_DONE)
        await emit(session_id, "supervisor", "error", "Tell us what to change before revising this episode.")
        return

    async def emit_token(_token: str):
        return None

    raw, _ = await with_resilience(
        stage="episode_revision",
        provider="openai",
        fn=lambda: analyze_change_impact(
            session.creative_dna,
            episode.production_script,
            instruction,
            feedback.keep.split("\n") if feedback.keep else session.creative_dna.non_negotiables,
            emit_token,
        ),
        fallback_fn=lambda: {"changed_lines": []},
        emit_fallback=lambda message: emit(session_id, "supervisor", "fallback", message),
    )
    changed = raw.get("changed_lines", []) if isinstance(raw, dict) else []
    revised = episode.production_script.model_copy(deep=True)
    for change in changed:
        index = change.get("line_index") if isinstance(change, dict) else None
        line = change.get("line") if isinstance(change, dict) else None
        if isinstance(index, int) and 0 <= index < len(revised.lines) and isinstance(line, dict):
            revised.lines[index] = ProductionLine.model_validate(line)
    episode.production_script = revised
    episode.constitution_report = await run_constitution_check(session_id, session.creative_dna, revised, episode_number)
    _clear_episode_media(episode)
    episode.status = EpisodeStatus.DRAFT_READY
    # A future draft depends on the old ending; do not silently rewrite an
    # already approved episode, but make unapproved future work honest.
    for future in session.episodes:
        if future.number > episode_number and future.status != EpisodeStatus.APPROVED:
            future.status = EpisodeStatus.STALE
            future.production_script = None
            future.constitution_report = None
            _clear_episode_media(future)
    _sync_legacy_episode_fields(session, episode)
    update_status(session, WorkflowStatus.CONSTITUTION_DONE)
    await emit(session_id, "supervisor", "artifact", {"episode": episode.model_dump()})
    await emit(session_id, "supervisor", "complete", {
        "status": "EPISODE_DRAFT_READY",
        "episode_number": episode_number,
    })


# ─── Main Produce Workflow ────────────────────────────────────────────────────

async def run_produce_workflow(session_id: str):
    """Called as a background task after /produce is hit."""
    s = load_session(session_id)
    if not s:
        return

    sid = session_id
    try:
        # 1. DNA already extracted — generate visions
        if s.creative_dna and s.status == WorkflowStatus.DNA_EXTRACTED:
            visions = await run_vision_generation(sid, s.creative_dna)
            s.visions = visions
            update_status(s, WorkflowStatus.VISIONS_READY)

        # 2. Vision selected — generate script
        # /produce records the creator's selection before this background
        # workflow starts, so VISION_SELECTED is the valid transition here.
        if s.selected_vision and s.visions and s.status == WorkflowStatus.VISION_SELECTED:
            script = await run_script_generation(sid, s.creative_dna, s.selected_vision, s.visions)
            s.production_script = script
            update_status(s, WorkflowStatus.SCRIPT_DRAFTED)

            # 3. Constitution check
            report = await run_constitution_check(sid, s.creative_dna, script)
            s.constitution_report = report
            update_status(s, WorkflowStatus.CONSTITUTION_DONE)

            # 4. Audio render
            cameo = s.voice_cameo
            update_status(s, WorkflowStatus.AUDIO_RENDERING)
            url = await run_audio_render(
                sid, script,
                cameo.voice_id if cameo else None,
                ("NARRATOR" if cameo and cameo.assigned_to == "narrator" else cameo.character_name) if cameo else None,
                s.preferences.voice_cast,
            )
            s.audio_url = url or None
            if url:
                update_status(s, WorkflowStatus.AUDIO_RENDERED)
                update_status(s, WorkflowStatus.READY)
                completion = {"status": "READY", "audio_url": url}
            else:
                # An unavailable voice provider must not make the episode look
                # finished. The approved script remains retryable.
                update_status(s, WorkflowStatus.CONSTITUTION_DONE)
                completion = {"status": "SCRIPT_READY", "audio_url": None}
        else:
            completion = {"status": s.status.value, "audio_url": s.audio_url}

        await emit(sid, "supervisor", "complete", completion)

    except Exception as exc:
        log.exception("Workflow error for session %s: %s", sid, exc)
        update_status(s, WorkflowStatus.ERROR)
        await emit(sid, "supervisor", "error", str(exc))
    finally:
        await close_stream(sid)


# ─── Revision Workflow ────────────────────────────────────────────────────────

async def run_revision_workflow(session_id: str, change_req: ChangeRequest):
    s = load_session(session_id)
    if not s or not s.production_script or not s.creative_dna:
        return

    sid = session_id
    try:
        await emit(sid, "supervisor", "status", "Keeping the details you chose...")

        if NOLAN_MODE == "replay":
            diff = FIXTURE_REVISION_DIFF
        else:
            async def emit_token(t: str):
                await emit(sid, "supervisor", "token", t)

            async def live():
                return await analyze_change_impact(
                    s.creative_dna, s.production_script,
                    change_req.change_instruction,
                    change_req.preserve_elements,
                    emit_token,
                )

            raw, _ = await with_resilience(
                stage="revision", provider="openai", fn=live,
                fallback_fn=lambda: {
                    "change_request": change_req.change_instruction,
                    "affected_scene_ids": ["pilot-opening", "pilot-cliffhanger"],
                    "preserved_elements": change_req.preserve_elements or s.creative_dna.non_negotiables,
                    "locked_elements": s.creative_dna.locked_fields,
                    "changed_scenes": [],
                },
                emit_fallback=lambda msg: emit(sid, "supervisor", "fallback", msg),
            )
            # The model returns a compact diff with changed_lines. Add the
            # request metadata that is known locally, then validate/persist the
            # full shape instead of rejecting every live revision.
            if not isinstance(raw, dict):
                raise TypeError("Revision analysis returned an invalid diff")
            diff = CreativeLockDiff.model_validate({
                **raw,
                "change_request": raw.get("change_request") or change_req.change_instruction,
                "changed_scenes": raw.get("changed_scenes") or [],
            })

        s.creative_lock_diff = diff
        save_session(s)

        await emit(sid, "supervisor", "artifact", {
            "lock_diff": diff.model_dump()
        })

        # Apply only model-identified line replacements, then re-check the changed
        # script. Previously this path showed a diff but rendered the old audio.
        changed_lines = diff.changed_lines
        if changed_lines:
            revised = s.production_script.model_copy(deep=True)
            invalid_indexes = [
                change.line_index for change in changed_lines
                if change.line_index >= len(revised.lines)
            ]
            if invalid_indexes:
                raise ValueError(
                    "Revision contains invalid production line indexes: "
                    + ", ".join(str(index) for index in invalid_indexes)
                )
            for change in changed_lines:
                revised.lines[change.line_index] = change.line.model_copy(deep=True)
            s.production_script = revised
            s.constitution_report = await run_constitution_check(sid, s.creative_dna, revised)
            update_status(s, WorkflowStatus.SCENES_REWRITTEN)

        # Re-render audio with actual changed production script.
        update_status(s, WorkflowStatus.AUDIO_RENDERING)
        url = await run_audio_render(
            sid, s.production_script,
            s.voice_cameo.voice_id if s.voice_cameo else None,
            ("NARRATOR" if s.voice_cameo and s.voice_cameo.assigned_to == "narrator" else s.voice_cameo.character_name) if s.voice_cameo else None,
            s.preferences.voice_cast,
        )
        s.audio_url = url or None
        if url:
            update_status(s, WorkflowStatus.READY)
            completion = {"status": "READY", "audio_url": url}
        else:
            update_status(s, WorkflowStatus.CONSTITUTION_DONE)
            completion = {"status": "SCRIPT_READY", "audio_url": None}
        await emit(sid, "supervisor", "complete", completion)

    except Exception as exc:
        log.exception("Revision error for session %s: %s", sid, exc)
        update_status(s, WorkflowStatus.ERROR)
        await emit(sid, "supervisor", "error", str(exc))
    finally:
        await close_stream(sid)
