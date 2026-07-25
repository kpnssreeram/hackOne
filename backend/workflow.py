"""
Workflow — deterministic state machine that orchestrates all agents.
Each stage streams tokens via SSE queue, has a hard timeout + circuit breaker fallback.
"""
from __future__ import annotations
import asyncio, json, os, uuid
from pathlib import Path
from typing import Callable, Awaitable
from schemas import (
    Session, WorkflowStatus, CreativeDNA, VisionCard,
    VisionSelection, ProductionScript, ConstitutionReport,
    CreativeLockDiff, ChangeRequest,
)
from resilience import with_resilience
from fixtures import FIXTURE_REVISION_DIFF
from agents.muse import extract_dna, _fallback_dna_from_transcript
from agents.writer import generate_visions, generate_script, _dynamic_vision_fallback
from agents.supervisor import check_constitution, analyze_change_impact, _dynamic_constitution_fallback
from agents.audio_director import generate_voice_lines
from agents.voice_cameo import clone_voice, preview_cameo, delete_cameo
from audio_mixer import mix_timeline
import logging

log = logging.getLogger("nolan.workflow")
NOLAN_MODE = os.getenv("NOLAN_MODE", "hybrid")
SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


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
    q = get_queue(session_id)
    await q.put(None)


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

async def run_transcription(session_id: str, audio_bytes: bytes) -> str:
    sid = session_id
    await emit(sid, "muse", "status", "Transcribing your idea...")

    if NOLAN_MODE == "replay":
        from fixtures import FIXTURE_TRANSCRIPT
        return FIXTURE_TRANSCRIPT

    async def live():
        import io
        file = ("idea.webm", io.BytesIO(audio_bytes), "audio/webm")
        resp = await oai.audio.transcriptions.create(
            model="whisper-1",
            file=file,
            language="en",
            prompt="Indian English. Speaker may use South Asian accent and phrasing.",
        )
        return resp.text

    text, degraded = await with_resilience(
        stage="transcribe", provider="openai", fn=live,
        fallback_fn=lambda: get_fixture("transcribe")["transcript"],
        emit_fallback=lambda msg: emit(sid, "muse", "fallback", msg),
    )
    if degraded:
        s = load_session(sid)
        if s:
            s.is_degraded = True
            s.degraded_stages.append("transcribe")
            save_session(s)
    await emit(sid, "muse", "artifact", {"transcript": text})
    return text


async def run_dna_extraction(session_id: str, transcript: str) -> CreativeDNA:
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
        return await extract_dna(transcript, emit_token)

    dna, degraded = await with_resilience(
        stage="dna", provider="openai", fn=live,
        fallback_fn=lambda: _fallback_dna_from_transcript(transcript),
        emit_fallback=lambda msg: emit(sid, "muse", "fallback", msg),
    )
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
) -> ProductionScript:
    sid = session_id
    await emit(sid, "writer", "status", "Composing production script...")

    if NOLAN_MODE == "replay":
        await emit(sid, "writer", "artifact", FIXTURE_PRODUCTION_SCRIPT.model_dump())
        return FIXTURE_PRODUCTION_SCRIPT

    async def emit_token(t: str):
        await emit(sid, "writer", "token", t)

    async def live():
        return await generate_script(dna, selection, visions, emit_token)

    def dynamic_script_fallback() -> ProductionScript:
        name = dna.protagonist.name.upper()
        counterpart = next((c.name.upper() for c in dna.characters if c.name.lower() != dna.protagonist.name.lower()), "VOICE")
        return ProductionScript(
            title=f"{dna.protagonist.name}: The First Turning",
            estimated_duration_seconds=70,
            lines=[
                {"type": "ambience", "description": f"atmosphere of {dna.genre[0] if dna.genre else 'an intimate drama'}", "duration_seconds": 2},
                {"type": "dialogue", "character": name, "text": dna.central_conflict, "emotion": dna.core_emotion},
                {"type": "silence", "duration_seconds": 1},
                {"type": "dialogue", "character": counterpart, "text": dna.non_negotiables[0] if dna.non_negotiables else "You are asking the wrong question.", "emotion": "guarded"},
                {"type": "music", "description": "a single unresolved musical turn", "duration_seconds": 3},
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
) -> ConstitutionReport:
    sid = session_id
    await emit(sid, "supervisor", "status", "Running Pocket FM Story Constitution...")

    if NOLAN_MODE == "replay":
        for check in FIXTURE_CONSTITUTION.checks:
            await emit(sid, "supervisor",
                       "violation" if not check.passed else "artifact",
                       check.model_dump())
        await emit(sid, "supervisor", "artifact", FIXTURE_CONSTITUTION.model_dump())
        return FIXTURE_CONSTITUTION

    async def emit_token(t: str):
        await emit(sid, "supervisor", "token", t)

    async def live():
        return await check_constitution(dna, script, emit_token)

    report, _ = await with_resilience(
        stage="constitution", provider="openai", fn=live,
        fallback_fn=lambda: _dynamic_constitution_fallback(script),
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
) -> str:
    """Render final audio. Returns URL path like /audio/{session_id}/pilot.mp3"""
    sid = session_id
    await emit(sid, "audio_director", "status", "Rendering cinematic audio pilot...")

    audio_dir = SESSIONS_DIR / sid / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    out_path = audio_dir / "pilot.mp3"

    if NOLAN_MODE == "replay":
        # Use precomputed demo audio if exists
        demo_audio = Path(__file__).parent.parent / "demo-fixtures" / "audio" / "pilot.mp3"
        if demo_audio.exists():
            import shutil
            shutil.copy(str(demo_audio), str(out_path))
            await emit(sid, "audio_director", "complete", {"url": f"/audio/{sid}/pilot.mp3"})
            return f"/audio/{sid}/pilot.mp3"

    async def live():
        tts_dir = audio_dir / "lines"
        tts_dir.mkdir(exist_ok=True)
        timeline = await generate_voice_lines(
            script, cameo_voice_id, cameo_character,
            lambda t: emit(sid, "audio_director", "token", t),
            tts_dir,
        )
        mix_timeline(timeline, out_path)
        return f"/audio/{sid}/pilot.mp3"

    url, _ = await with_resilience(
        stage="audio", provider="elevenlabs", fn=live,
        fallback_fn=lambda: f"/audio/{sid}/pilot.mp3",
        emit_fallback=lambda msg: emit(sid, "audio_director", "fallback", msg),
    )
    await emit(sid, "audio_director", "complete", {"url": url})
    return url


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
        if s.selected_vision and s.visions and s.status == WorkflowStatus.VISIONS_READY:
            script = await run_script_generation(sid, s.creative_dna, s.selected_vision, s.visions)
            s.production_script = script
            update_status(s, WorkflowStatus.SCRIPT_DRAFTED)

            # 3. Constitution check
            report = await run_constitution_check(sid, s.creative_dna, script)
            s.constitution_report = report
            update_status(s, WorkflowStatus.CONSTITUTION_DONE)

            # 4. Audio render
            cameo = s.voice_cameo
            url = await run_audio_render(
                sid, script,
                cameo.voice_id if cameo else None,
                cameo.assigned_to if cameo else None,
            )
            s.audio_url = url
            update_status(s, WorkflowStatus.AUDIO_RENDERED)
            update_status(s, WorkflowStatus.READY)

        await emit(sid, "supervisor", "complete", {"status": "READY", "audio_url": s.audio_url})

    except Exception as exc:
        log.exception("Workflow error for session %s: %s", sid, exc)
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
        await emit(sid, "supervisor", "status", "Activating Semantic Creative Lock...")

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
            diff = raw

        s.creative_lock_diff = diff if not isinstance(diff, dict) else CreativeLockDiff.model_validate(diff)
        save_session(s)

        await emit(sid, "supervisor", "artifact", {
            "lock_diff": diff if isinstance(diff, dict) else diff.model_dump()
        })

        # Re-render audio with changes
        url = await run_audio_render(
            sid, s.production_script,
            s.voice_cameo.voice_id if s.voice_cameo else None,
            s.voice_cameo.assigned_to if s.voice_cameo else None,
        )
        s.audio_url = url
        update_status(s, WorkflowStatus.READY)
        await emit(sid, "supervisor", "complete", {"status": "READY", "audio_url": url})

    except Exception as exc:
        log.exception("Revision error for session %s: %s", sid, exc)
        await emit(sid, "supervisor", "error", str(exc))
    finally:
        await close_stream(sid)
