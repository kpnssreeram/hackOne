"""
Nolan — FastAPI backend
All endpoints, SSE streaming, file serving.
"""
from __future__ import annotations
import asyncio, json, os, uuid, io, shutil, subprocess
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from schemas import (
    Session, WorkflowStatus, CreativeDNA, VisionSelection,
    ChangeRequest, EpisodeFeedback, EpisodeStatus, VoiceCameoConsent,
    ConstitutionRepairBody, ProductionScript,
    SessionPreferences, VisualAsset,
)
from workflow import (
    load_session, save_session, update_status, get_queue,
    run_transcription, run_dna_extraction,
    run_confirmed_episode_render, run_continue_series, run_episode_draft,
    run_episode_revision, run_produce_workflow, run_revision_workflow,
    run_series_outline, run_audio_render,
    apply_constitution_repair_to_script, _clear_episode_media, _sync_legacy_episode_fields,
    SESSIONS_DIR, emit,
)
from agents.voice_cameo import VoiceClonePlanRequired, clone_voice, preview_cameo, delete_cameo
from agents.audio_director import list_account_voices
from agents.visual_director import (
    fallback_cover_svg, generate_episode_cover, plan_visual_episode,
    start_video_teaser, wait_for_video_teaser,
)
from schemas import VisualEpisodeResult
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("nolan.main")

NOLAN_MODE = os.getenv("NOLAN_MODE", "hybrid")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
AUDIO_DIR = SESSIONS_DIR
VISUAL_ASSET_NAMES = {"portrait", "live_video"}
VISUAL_ASSET_KINDS = {"photo", "video", "place_reference"}
SERIES_VIDEO_SLOTS = {"video_1", "video_2"}
IMAGE_MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_MEDIA_SUFFIXES = {".mp4", ".webm", ".mov"}
IN_FLIGHT_STATUSES = {
    WorkflowStatus.VISION_GENERATING,
    WorkflowStatus.VISION_SELECTED,
    WorkflowStatus.SCRIPT_DRAFTED,
    WorkflowStatus.AUDIO_RENDERING,
    WorkflowStatus.REVISING,
}


def _validated_session_id(session_id: str) -> str:
    """Accept only canonical session IDs before constructing file paths."""
    try:
        parsed = uuid.UUID(session_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(400, "Invalid session ID")
    if str(parsed) != session_id:
        raise HTTPException(400, "Invalid session ID")
    return session_id


def _validated_filename(filename: str) -> str:
    """Reject path components instead of relying on path joining behaviour."""
    if not filename or filename in {".", ".."} or Path(filename).name != filename or Path(filename).is_absolute():
        raise HTTPException(400, "Invalid filename")
    return filename


def _safe_media_suffix(filename: str | None, *, image: bool) -> str:
    """Keep uploaded media safe to serve directly from Nolan's media route."""
    suffix = Path(filename or "").suffix.lower()
    allowed = IMAGE_MEDIA_SUFFIXES if image else VIDEO_MEDIA_SUFFIXES
    if suffix and suffix not in allowed:
        allowed_names = "JPG, PNG, or WEBP" if image else "MP4, WEBM, or MOV"
        raise HTTPException(422, f"Use a supported {allowed_names} file")
    return suffix or (".jpg" if image else ".mp4")


def _series_video_assets(session: Session) -> list[VisualAsset]:
    """Return the two explicitly uploaded source videos, in slot order."""
    return [
        next(
            (
                asset for asset in session.visual_assets
                if asset.kind == "video" and asset.consented and asset.filename.startswith(f"series-{slot}-")
            ),
            None,
        )
        for slot in ("video_1", "video_2")
    ]


def _has_two_series_videos(session: Session) -> bool:
    return all(_series_video_assets(session))


def _ffmpeg_path() -> str | None:
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _prepared_place_reference(session_id: str, assets: list[VisualAsset], episode_number: int | None) -> Path | None:
    """Make a portrait location image legal for Sora's 720x1280 input frame."""
    asset = next((item for item in assets if item.kind == "place_reference" and item.consented), None)
    if not asset:
        return None
    source = SESSIONS_DIR / session_id / "visual" / asset.filename
    ffmpeg = _ffmpeg_path()
    if not source.exists() or not ffmpeg:
        return None
    target = SESSIONS_DIR / session_id / "visual" / f"episode-{episode_number or 1}-reference.jpg"
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(source), "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280", "-frames:v", "1", str(target)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return target if target.exists() else None
    except Exception as exc:
        log.warning("Could not prepare place reference: %s", exc)
        return None


def _compose_episode_video(session_id: str, episode, scene_path: Path) -> Path | None:
    """Deliver one playable episode: generated scene on video, Nolan mix on audio."""
    if not episode or not episode.audio_url:
        return None
    ffmpeg = _ffmpeg_path()
    audio_path = SESSIONS_DIR / session_id / "audio" / Path(episode.audio_url).name
    if not ffmpeg or not scene_path.exists() or not audio_path.exists():
        return None
    output = SESSIONS_DIR / session_id / "visual" / f"episode-{episode.number}.mp4"
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-stream_loop", "-1", "-i", str(scene_path), "-i", str(audio_path),
                "-map", "0:v:0", "-map", "1:a:0", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart", str(output),
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return output if output.exists() else None
    except Exception as exc:
        log.warning("Could not compose episode video: %s", exc)
        return None


def _compose_uploaded_video_episode(session_id: str, episode) -> Path | None:
    """Cut the two required creator videos into one audio-length episode."""
    if not episode or not episode.audio_url:
        return None
    ffmpeg = _ffmpeg_path()
    session = load_session(session_id)
    if not session:
        return None
    assets = _series_video_assets(session)
    paths = [SESSIONS_DIR / session_id / "visual" / asset.filename for asset in assets]
    audio_path = SESSIONS_DIR / session_id / "audio" / Path(episode.audio_url).name
    if not ffmpeg or len(paths) != 2 or not all(path.exists() for path in paths) or not audio_path.exists():
        return None
    output = SESSIONS_DIR / session_id / "visual" / f"episode-{episode.number}.mp4"
    try:
        from audio_mixer import _decode_mp3
        duration = max(60.0, len(_decode_mp3(audio_path)) / 1000)
    except Exception:
        duration = max(60.0, float(episode.actual_duration_seconds or 90))
    first_half = round(duration / 2, 3)
    second_half = round(duration - first_half, 3)
    scale = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,format=yuv420p"
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-stream_loop", "-1", "-i", str(paths[0]),
                "-stream_loop", "-1", "-i", str(paths[1]), "-i", str(audio_path),
                "-filter_complex",
                f"[0:v]{scale},trim=duration={first_half},setpts=PTS-STARTPTS[v0];"
                f"[1:v]{scale},trim=duration={second_half},setpts=PTS-STARTPTS[v1];"
                "[v0][v1]concat=n=2:v=1:a=0[v]",
                "-map", "[v]", "-map", "2:a:0", "-t", str(duration),
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart", str(output),
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return output if output.exists() else None
    except Exception as exc:
        log.warning("Could not compose uploaded video episode: %s", exc)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Nolan backend starting — mode=%s", NOLAN_MODE)
    yield
    log.info("Nolan backend shutdown")


app = FastAPI(title="Nolan", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "mode": NOLAN_MODE}


# ─── Sessions ─────────────────────────────────────────────────────────────────

@app.post("/api/sessions")
async def create_session():
    sid = str(uuid.uuid4())
    s = Session(id=sid, mode=NOLAN_MODE)
    save_session(s)
    log.info("Session created: %s", sid)
    return {"session_id": sid, "mode": NOLAN_MODE}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return s.model_dump()


# ─── Idea Audio ───────────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/idea-audio")
async def submit_idea_audio(session_id: str, audio: UploadFile = File(...), language: str | None = Form(None)):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")

    audio_bytes = await audio.read()
    transcript, detected_language = await run_transcription(session_id, audio_bytes, language)

    s.transcript = transcript
    s.detected_input_language = detected_language
    update_status(s, WorkflowStatus.TRANSCRIBED)
    return {"transcript": transcript, "detected_input_language": detected_language}


# ─── Creative DNA ─────────────────────────────────────────────────────────────

class TranscriptBody(BaseModel):
    transcript: str
    output_language: str | None = None

@app.post("/api/sessions/{session_id}/extract-dna")
async def extract_dna_endpoint(session_id: str, body: TranscriptBody):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")

    s.transcript = body.transcript.strip()
    if not s.transcript:
        raise HTTPException(422, "Please provide a story idea before continuing")
    if body.output_language:
        s.preferences.output_language = body.output_language
    dna = await run_dna_extraction(session_id, s.transcript, s.preferences.output_language)
    s.creative_dna = dna
    update_status(s, WorkflowStatus.DNA_EXTRACTED)
    return dna.model_dump()


class DNAUpdateBody(BaseModel):
    creative_dna: CreativeDNA

@app.put("/api/sessions/{session_id}/creative-dna")
async def update_dna(session_id: str, body: DNAUpdateBody):
    """Creator edits/locks DNA fields."""
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    s.creative_dna = body.creative_dna
    save_session(s)
    return s.creative_dna.model_dump()

@app.put("/api/sessions/{session_id}/preferences")
async def update_preferences(session_id: str, body: SessionPreferences):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    s.preferences = body
    save_session(s)
    return s.preferences.model_dump()


@app.get("/api/voices")
async def get_account_voices():
    """Expose only safe voice metadata for the creator's casting picker."""
    try:
        return {"voices": await list_account_voices()}
    except RuntimeError as exc:
        raise HTTPException(503, "ElevenLabs voices are temporarily unavailable") from exc


# ─── Visions + Produce ────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/generate-visions")
async def generate_visions_endpoint(session_id: str, background_tasks: BackgroundTasks):
    s = load_session(session_id)
    if not s or not s.creative_dna:
        raise HTTPException(400, "DNA not extracted yet")
    if s.status == WorkflowStatus.VISION_GENERATING:
        raise HTTPException(409, "Vision generation is already in progress")
    if s.status != WorkflowStatus.DNA_EXTRACTED:
        raise HTTPException(409, "Generate a new story brief before creating visions")

    async def _run():
        from workflow import run_vision_generation, emit, close_stream
        try:
            visions = await run_vision_generation(session_id, s.creative_dna)
            s.visions = visions
            update_status(s, WorkflowStatus.VISIONS_READY)
            await emit(session_id, "writer", "complete", {"visions_count": len(visions)})
        except Exception as exc:
            log.exception("Vision generation error for session %s: %s", session_id, exc)
            # Keep the completed DNA available for a clean retry.
            update_status(s, WorkflowStatus.DNA_EXTRACTED)
            await emit(session_id, "writer", "error", str(exc))
        finally:
            await close_stream(session_id)

    update_status(s, WorkflowStatus.VISION_GENERATING)
    background_tasks.add_task(_run)
    return {"status": "generating"}


class SelectionBody(BaseModel):
    vision_selection: VisionSelection


class EpisodeFeedbackBody(BaseModel):
    action: str
    feedback: EpisodeFeedback


class EpisodeScriptBody(BaseModel):
    production_script: ProductionScript


class CoverImageBody(BaseModel):
    poster_prompt: str = Field(default="", max_length=2000)


def _series_episode(session: Session, episode_number: int):
    return next((episode for episode in session.episodes if episode.number == episode_number), None)


@app.post("/api/sessions/{session_id}/series")
async def create_series_plan(session_id: str, body: SelectionBody, background_tasks: BackgroundTasks):
    """Plan all three episodes first; no audio or visuals are spent here."""
    s = load_session(session_id)
    if not s or not s.creative_dna or not s.visions:
        raise HTTPException(409, "Choose a story direction before planning the series")
    if s.status in IN_FLIGHT_STATUSES:
        raise HTTPException(409, "A story task is already in progress")
    selection_ids = {
        body.vision_selection.primary_vision_id,
        body.vision_selection.opening_from,
        body.vision_selection.relationship_from,
        body.vision_selection.ending_from,
    }
    available_ids = {vision.id for vision in s.visions}
    if selection_ids - available_ids:
        raise HTTPException(422, "Choose only from this session's story directions")
    s.selected_vision = body.vision_selection
    s.series_plan = None
    s.episodes = []
    s.active_episode_number = 1
    # A new three-part plan must never inherit a prior pilot's audio or review.
    s.production_script = None
    s.constitution_report = None
    s.creative_lock_diff = None
    s.audio_url = None
    s.cover_image_url = None
    s.visual_episode_plan = None
    s.visual_episode = None
    update_status(s, WorkflowStatus.VISION_SELECTED)
    background_tasks.add_task(run_series_outline, session_id)
    return {"status": "planning_series"}


@app.post("/api/sessions/{session_id}/episodes/{episode_number}/draft")
async def draft_episode(session_id: str, episode_number: int, background_tasks: BackgroundTasks):
    s = load_session(session_id)
    if not s or not s.series_plan:
        raise HTTPException(409, "Plan the three-episode story first")
    episode = _series_episode(s, episode_number)
    if not episode:
        raise HTTPException(404, "Episode not found")
    if episode_number > 1:
        previous = _series_episode(s, episode_number - 1)
        if not previous or previous.status != EpisodeStatus.APPROVED:
            raise HTTPException(409, "Approve the previous episode before drafting this one")
    if s.status in IN_FLIGHT_STATUSES or episode.status not in {EpisodeStatus.OUTLINED, EpisodeStatus.STALE}:
        raise HTTPException(409, "This episode already has a draft in progress or ready for review")
    episode.status = EpisodeStatus.DRAFTING
    s.active_episode_number = episode_number
    update_status(s, WorkflowStatus.SCRIPT_DRAFTED)
    background_tasks.add_task(run_episode_draft, session_id, episode_number)
    return {"status": "drafting", "episode_number": episode_number}


@app.post("/api/sessions/{session_id}/episodes/{episode_number}/confirm")
async def confirm_episode(session_id: str, episode_number: int, background_tasks: BackgroundTasks):
    """Creator confirmation gate before audio generation uses credits."""
    s = load_session(session_id)
    episode = _series_episode(s, episode_number) if s else None
    if not s or not episode:
        raise HTTPException(404, "Episode not found")
    if episode.status != EpisodeStatus.DRAFT_READY or not episode.production_script:
        raise HTTPException(409, "Review the episode draft before creating its audio")
    if s.preferences.output_mode == "video" and not _has_two_series_videos(s):
        raise HTTPException(409, "Video series requires both source videos before an episode can be generated")
    if s.status in IN_FLIGHT_STATUSES:
        raise HTTPException(409, "This story task is already in progress")
    episode.status = EpisodeStatus.RENDERING
    s.active_episode_number = episode_number
    update_status(s, WorkflowStatus.AUDIO_RENDERING)
    background_tasks.add_task(run_confirmed_episode_render, session_id, episode_number)
    return {"status": "rendering", "episode_number": episode_number}


@app.post("/api/sessions/{session_id}/episodes/{episode_number}/feedback")
async def episode_feedback(
    session_id: str,
    episode_number: int,
    body: EpisodeFeedbackBody,
    background_tasks: BackgroundTasks,
):
    """Either improve this episode or carry creator direction into the next one."""
    s = load_session(session_id)
    episode = _series_episode(s, episode_number) if s else None
    if not s or not episode:
        raise HTTPException(404, "Episode not found")
    if s.status in IN_FLIGHT_STATUSES:
        raise HTTPException(409, "This story task is already in progress")
    if body.action == "revise":
        if not episode.production_script:
            raise HTTPException(409, "Draft this episode before revising it")
        if not body.feedback.change_this_episode.strip():
            raise HTTPException(422, "Tell us what to change before revising this episode")
        if any(
            future.number > episode_number and future.status == EpisodeStatus.APPROVED
            for future in s.episodes
        ):
            raise HTTPException(409, "Revise the latest approved episode to preserve story continuity")
        episode.status = EpisodeStatus.REVISING
        s.active_episode_number = episode_number
        update_status(s, WorkflowStatus.REVISING)
        background_tasks.add_task(run_episode_revision, session_id, episode_number, body.feedback)
        return {"status": "revising", "episode_number": episode_number}
    if body.action == "continue":
        if episode.status != EpisodeStatus.READY:
            raise HTTPException(409, "Listen to the finished episode before continuing")
        # Reserve the session before the background task starts so a second tap
        # cannot create two concurrent next-episode drafts.
        update_status(s, WorkflowStatus.SCRIPT_DRAFTED)
        background_tasks.add_task(run_continue_series, session_id, episode_number, body.feedback)
        return {"status": "continuing", "episode_number": episode_number}
    raise HTTPException(422, "action must be revise or continue")


@app.post("/api/sessions/{session_id}/episodes/{episode_number}/constitution-repair")
async def constitution_repair(
    session_id: str,
    episode_number: int,
    body: ConstitutionRepairBody,
):
    """Apply a Constitution suggestion immediately, without a model revision pass."""
    s = load_session(session_id)
    episode = _series_episode(s, episode_number) if s else None
    if not s or not episode:
        raise HTTPException(404, "Episode not found")
    if not episode.production_script or not episode.constitution_report:
        raise HTTPException(409, "Draft and check this episode before applying a repair")
    if s.status in IN_FLIGHT_STATUSES:
        raise HTTPException(409, "This story task is already in progress")
    if any(
        future.number > episode_number and future.status == EpisodeStatus.APPROVED
        for future in s.episodes
    ):
        raise HTTPException(409, "Revise the latest approved episode to preserve story continuity")

    check = next((item for item in episode.constitution_report.checks if item.rule_number == body.rule_number), None)
    if not check:
        raise HTTPException(404, "Constitution rule not found")
    if check.passed:
        return {"status": "already_fixed", "episode": episode.model_dump()}

    episode.production_script = apply_constitution_repair_to_script(episode.production_script, body.repair)
    repaired_checks = [
        item.model_copy(update={
            "passed": True,
            "evidence": f"Applied repair: {body.repair[:240]}",
            "reason": None,
            "repair": None,
        }) if item.rule_number == body.rule_number else item
        for item in episode.constitution_report.checks
    ]
    passed_count = sum(1 for item in repaired_checks if item.passed)
    episode.constitution_report = episode.constitution_report.model_copy(update={
        "checks": repaired_checks,
        "overall_score": round(passed_count / max(1, len(repaired_checks)) * 100),
        "repaired_script_patch": body.repair,
    })
    # Keep an already generated audio file available for immediate playback;
    # the repaired script is visible now and can be rendered as a new take later.
    s.active_episode_number = episode_number
    update_status(s, WorkflowStatus.READY if episode.audio_url else WorkflowStatus.CONSTITUTION_DONE)
    await emit(session_id, "supervisor", "artifact", {"episode": episode.model_dump()})
    await emit(session_id, "supervisor", "repair", {
        "episode_number": episode_number,
        "rule_number": body.rule_number,
        "message": f"Rule {body.rule_number} repaired immediately.",
    })
    return {"status": "repaired", "episode": episode.model_dump()}


@app.put("/api/sessions/{session_id}/episodes/{episode_number}/script")
async def update_episode_script(session_id: str, episode_number: int, body: EpisodeScriptBody):
    """Save the creator's screenplay edits; the next render uses these exact cues."""
    s = load_session(session_id)
    episode = _series_episode(s, episode_number) if s else None
    if not s or not episode:
        raise HTTPException(404, "Episode not found")
    if s.status in IN_FLIGHT_STATUSES:
        raise HTTPException(409, "A story task is already in progress")
    if any(item.number > episode_number and item.status == EpisodeStatus.APPROVED for item in s.episodes):
        raise HTTPException(409, "Edit the latest approved episode to preserve story continuity")
    if not body.production_script.lines:
        raise HTTPException(422, "A screenplay needs at least one line")

    episode.production_script = body.production_script
    _clear_episode_media(episode)
    episode.status = EpisodeStatus.DRAFT_READY
    _sync_legacy_episode_fields(s, episode)
    update_status(s, WorkflowStatus.CONSTITUTION_DONE)
    save_session(s)
    await emit(session_id, "writer", "artifact", {"episode": episode.model_dump()})
    return {"status": "script_updated", "episode": episode.model_dump()}

@app.post("/api/sessions/{session_id}/produce")
async def produce(session_id: str, body: SelectionBody, background_tasks: BackgroundTasks):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if not s.creative_dna or not s.visions:
        raise HTTPException(409, "Generate directorial visions before producing an episode")
    if s.status in IN_FLIGHT_STATUSES:
        raise HTTPException(409, "An episode workflow is already in progress for this session")

    selection_ids = {
        body.vision_selection.primary_vision_id,
        body.vision_selection.opening_from,
        body.vision_selection.relationship_from,
        body.vision_selection.ending_from,
    }
    available_ids = {vision.id for vision in s.visions}
    invalid_ids = selection_ids - available_ids
    if invalid_ids:
        raise HTTPException(422, "Choose only from this session's generated visions")

    s.selected_vision = body.vision_selection
    # A new production must not let a poller mistake the previous pilot for
    # this run's completed audio.
    s.audio_url = None
    s.cover_image_url = None
    update_status(s, WorkflowStatus.VISION_SELECTED)
    background_tasks.add_task(run_produce_workflow, session_id)
    return {"status": "producing"}


@app.post("/api/sessions/{session_id}/render-audio")
async def render_audio(session_id: str, background_tasks: BackgroundTasks):
    """Retry only the final audio stage; never make a creator redo their story."""
    s = load_session(session_id)
    if not s or not s.production_script:
        raise HTTPException(400, "Create a production script before rendering audio")
    if s.status not in {WorkflowStatus.CONSTITUTION_DONE, WorkflowStatus.READY}:
        raise HTTPException(409, "Wait for the approved production script before rendering audio")

    s.audio_url = None
    update_status(s, WorkflowStatus.AUDIO_RENDERING)

    async def _run():
        cameo = s.voice_cameo
        url = await run_audio_render(
            session_id,
            s.production_script,
            cameo.voice_id if cameo else None,
            ("NARRATOR" if cameo and cameo.assigned_to == "narrator" else cameo.character_name) if cameo else None,
            s.preferences.voice_cast,
        )
        s.audio_url = url or None
        if url:
            update_status(s, WorkflowStatus.AUDIO_RENDERED)
            update_status(s, WorkflowStatus.READY)
            await emit(session_id, "supervisor", "complete", {"status": "READY", "audio_url": url})
        else:
            # Keep the approved script and make the retry affordance visible.
            update_status(s, WorkflowStatus.CONSTITUTION_DONE)
            await emit(session_id, "supervisor", "complete", {"status": "SCRIPT_READY", "audio_url": None})

    background_tasks.add_task(_run)
    return {"status": "rendering"}


# ─── Revision (Semantic Creative Lock) ───────────────────────────────────────

class ReviseBody(BaseModel):
    change_request: ChangeRequest

@app.post("/api/sessions/{session_id}/revise")
async def revise(session_id: str, body: ReviseBody, background_tasks: BackgroundTasks):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if not s.production_script or not s.creative_dna:
        raise HTTPException(409, "Create a production script before revising it")
    if s.status not in {WorkflowStatus.CONSTITUTION_DONE, WorkflowStatus.READY}:
        raise HTTPException(409, "An episode workflow is already in progress for this session")
    # Clear the old URL before the task starts so clients can distinguish this
    # revision from the already-rendered episode.
    s.audio_url = None
    s.cover_image_url = None
    update_status(s, WorkflowStatus.REVISING)
    background_tasks.add_task(run_revision_workflow, session_id, body.change_request)
    return {"status": "revising"}


# ─── SSE Event Stream ─────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/events")
async def stream_events(session_id: str):
    async def generator():
        q = get_queue(session_id)
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=60.0)
            except asyncio.TimeoutError:
                yield {"data": json.dumps({"agent": "system", "type": "ping", "data": ""})}
                continue
            if event is None:
                yield {"data": json.dumps({"agent": "system", "type": "close", "data": ""})}
                break
            yield {"data": json.dumps(event)}

    return EventSourceResponse(generator())


# ─── Voice Cameo ──────────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/voice-cameo/consent")
async def voice_cameo_consent(session_id: str, body: VoiceCameoConsent):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if not body.confirmed or (body.assigned_to == "character" and not body.character_name):
        raise HTTPException(422, "Confirm self-voice consent and choose a valid role")
    s.voice_cameo_consent = body
    save_session(s)
    return {"status": "consent_recorded"}

@app.post("/api/sessions/{session_id}/voice-cameo/clone")
async def voice_cameo_clone(session_id: str, audio: UploadFile = File(...)):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if not s.voice_cameo_consent or not s.voice_cameo_consent.confirmed:
        raise HTTPException(403, "Record explicit self-voice consent before uploading a clone sample")

    audio_bytes = await audio.read()
    try:
        voice_id, requires_verification = await clone_voice(audio_bytes, session_id)
    except VoiceClonePlanRequired:
        return {
            "success": False,
            "requires_upgrade": True,
            "message": (
                "Voice cloning needs an ElevenLabs Starter plan or above. "
                "You can still create this story with the voice you selected."
            ),
        }

    if not voice_id:
        return {"success": False, "message": "Voice cloning could not start — using the selected story voice"}

    if requires_verification:
        return {"success": False, "requires_verification": True,
                "message": "ElevenLabs requires manual verification for this voice"}

    # Store voice_id temporarily in session
    from schemas import VoiceCameoResult
    s.voice_cameo = VoiceCameoResult(
        voice_id=voice_id,
        assigned_to=s.voice_cameo_consent.assigned_to,
        character_name=s.voice_cameo_consent.character_name,
        preview_text="I see you, Maya. I am the only one who does.",
    )
    save_session(s)

    # A preview is helpful but must not discard a successfully consented clone
    # when a transient TTS request fails.
    try:
        preview_bytes = await preview_cameo(voice_id)
        preview_path = SESSIONS_DIR / session_id / "cameo_preview.mp3"
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_bytes(preview_bytes)
        preview_url = f"/audio/{session_id}/cameo_preview.mp3"
    except Exception as exc:
        log.warning("Voice Cameo preview failed for %s: %s", session_id, exc)
        preview_url = None

    return {"success": True, "voice_id": voice_id, "preview_url": preview_url}


@app.delete("/api/sessions/{session_id}/voice-cameo")
async def delete_voice_cameo(session_id: str):
    s = load_session(session_id)
    if not s or not s.voice_cameo:
        return {"status": "no cameo to delete"}
    await delete_cameo(s.voice_cameo.voice_id)
    s.voice_cameo = None
    save_session(s)
    return {"status": "deleted"}


# ─── Visual Episode ──────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/cover-image")
async def create_cover_image(session_id: str, body: CoverImageBody | None = None, episode_number: int | None = None):
    """Create one story-led cover; image-provider failures fall back to SVG."""
    session_id = _validated_session_id(session_id)
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    active_number = episode_number or s.active_episode_number
    active_episode = _series_episode(s, active_number) if s.episodes else None
    if episode_number is not None and not active_episode:
        raise HTTPException(404, "Episode not found")
    script = active_episode.production_script if active_episode else s.production_script
    if not s.creative_dna or not script:
        raise HTTPException(409, "Generate the approved production script before creating a cover")

    poster_reference = next(
        (asset for asset in reversed(s.visual_assets)
         if asset.kind == "photo" and asset.consented and asset.filename.startswith("poster-reference-")),
        None,
    )
    reference_path = SESSIONS_DIR / session_id / "visual" / poster_reference.filename if poster_reference else None
    poster_prompt = (body.poster_prompt if body else "").strip()
    image_bytes = await generate_episode_cover(s.creative_dna, script, reference_path, poster_prompt)
    stem = f"episode-{active_episode.number}-cover" if active_episode else "episode-cover"
    # If the image model is unavailable, retain the creator's actual image as
    # the backdrop instead of replacing it with a generic illustration. The UI
    # supplies the cinematic title and credits over that authored backdrop.
    using_reference_backdrop = not image_bytes and bool(reference_path and reference_path.exists())
    suffix = reference_path.suffix.lower() if using_reference_backdrop and reference_path else ".png" if image_bytes else ".svg"
    filename = f"{stem}{suffix}"
    content = image_bytes or (reference_path.read_bytes() if using_reference_backdrop and reference_path else fallback_cover_svg(s.creative_dna, script))
    destination = SESSIONS_DIR / session_id / "visual" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)

    url = f"/media/{session_id}/{filename}"
    s.cover_image_url = url
    s.poster_prompt = poster_prompt
    if active_episode:
        s.active_episode_number = active_episode.number
        active_episode.cover_image_url = url
        active_episode.poster_prompt = poster_prompt
    save_session(s)
    await emit(session_id, "visual_director", "artifact", {
        "cover_image_url": url,
        "generated": bool(image_bytes), "reference_backdrop": using_reference_backdrop,
    })
    cast = [s.creative_dna.protagonist.name] + [
        character.name for character in s.creative_dna.characters
        if character.name != s.creative_dna.protagonist.name
    ]
    return {
        "url": url,
        "generated": bool(image_bytes),
        "reference_backdrop": using_reference_backdrop,
        "metadata": {
            "title": script.title,
            "directed_by": "Nolan",
            "starring": cast,
        },
    }


@app.post("/api/sessions/{session_id}/poster-reference")
async def upload_poster_reference(
    session_id: str,
    asset: UploadFile = File(...),
    consent: bool = Form(False),
):
    """Store one compact, consented image reference for the next AI poster."""
    session_id = _validated_session_id(session_id)
    if not consent:
        raise HTTPException(400, "Confirm that you own this image and consent to its use for the poster")
    if not (asset.content_type or "").startswith("image/"):
        raise HTTPException(422, "Poster reference must be an image")
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    content = await asset.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "Keep poster references under 5 MB")

    asset_id = str(uuid.uuid4())
    suffix = _safe_media_suffix(asset.filename, image=True)
    filename = f"poster-reference-{asset_id[:8]}{suffix}"
    destination = SESSIONS_DIR / session_id / "visual" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    record = VisualAsset(
        id=asset_id,
        kind="photo",
        filename=filename,
        url=f"/media/{session_id}/{filename}",
        consented=True,
    )
    s.visual_assets = [
        item for item in s.visual_assets
        if not (item.kind == "photo" and item.filename.startswith("poster-reference-"))
    ] + [record]
    save_session(s)
    return record.model_dump()


@app.post("/api/sessions/{session_id}/series-videos/{slot}")
async def upload_series_video(
    session_id: str,
    slot: str,
    asset: UploadFile = File(...),
    consent: bool = Form(False),
):
    """Store one of the two required source videos for a video series."""
    if slot not in SERIES_VIDEO_SLOTS:
        raise HTTPException(400, "slot must be video_1 or video_2")
    if not consent:
        raise HTTPException(400, "Explicit consent is required for uploaded video media")
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if not (asset.content_type or "").startswith("video/"):
        raise HTTPException(422, "Both video series sources must be video files")

    suffix = _safe_media_suffix(asset.filename, image=False)
    asset_id = str(uuid.uuid4())
    filename = f"series-{slot}-{asset_id[:8]}{suffix}"
    destination = SESSIONS_DIR / session_id / "visual" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(await asset.read())
    # Replacing a slot keeps the series deterministic after a creator changes
    # one source video and avoids stale media being picked during the edit.
    s.visual_assets = [
        item for item in s.visual_assets
        if not item.filename.startswith(f"series-{slot}-")
    ] + [VisualAsset(
        id=asset_id,
        kind="video",
        filename=filename,
        url=f"/media/{session_id}/{filename}",
        consented=True,
    )]
    save_session(s)
    return {"slot": slot, "stored": True, "filename": filename}


@app.post("/api/sessions/{session_id}/visual-assets/{asset_name}")
async def upload_visual_asset(
    session_id: str,
    asset_name: str,
    asset: UploadFile = File(...),
    consent: bool = Form(False),
):
    """Store creator-owned source media. Portraits are never sent to Sora."""
    if asset_name not in VISUAL_ASSET_NAMES:
        raise HTTPException(400, "asset_name must be portrait or live_video")
    if not consent:
        raise HTTPException(400, "Explicit consent is required for uploaded visual media")
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if asset_name == "portrait" and not (asset.content_type or "").startswith("image/"):
        raise HTTPException(400, "Portrait must be an image")
    if asset_name == "live_video" and not (asset.content_type or "").startswith("video/"):
        raise HTTPException(400, "Live footage must be a video")

    suffix = _safe_media_suffix(asset.filename, image=asset_name == "portrait")
    destination = SESSIONS_DIR / session_id / "visual" / f"{asset_name}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(await asset.read())
    # Keep the original, simpler visual uploader useful in the new series
    # planner as well. These files are editorial assets—not prompts for a
    # person-generation model.
    legacy_kind = "photo" if asset_name == "portrait" else "video"
    record = VisualAsset(
        id=str(uuid.uuid4()),
        kind=legacy_kind,
        filename=destination.name,
        url=f"/media/{session_id}/{destination.name}",
        consented=True,
    )
    s.visual_assets = [item for item in s.visual_assets if item.filename != record.filename] + [record]
    save_session(s)
    return {"asset": asset_name, "stored": True, "filename": destination.name}


@app.post("/api/sessions/{session_id}/story-assets")
async def upload_story_asset(
    session_id: str,
    asset: UploadFile = File(...),
    kind: str = Form(...),
    consent: bool = Form(False),
):
    """Save optional creator media for direct placement in the visual story."""
    if kind not in VISUAL_ASSET_KINDS:
        raise HTTPException(422, "kind must be photo, video, or place_reference")
    if not consent:
        raise HTTPException(400, "Confirm that you own this media and consent to its use")
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    content_type = asset.content_type or ""
    needs_image = kind in {"photo", "place_reference"}
    if needs_image and not content_type.startswith("image/"):
        raise HTTPException(422, "A photo or place reference must be an image")
    if kind == "video" and not content_type.startswith("video/"):
        raise HTTPException(422, "A video asset must be a video file")

    asset_id = str(uuid.uuid4())
    suffix = _safe_media_suffix(asset.filename, image=needs_image)
    filename = f"story-{asset_id[:8]}{suffix}"
    destination = SESSIONS_DIR / session_id / "visual" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(await asset.read())
    record = VisualAsset(
        id=asset_id,
        kind=kind,
        filename=filename,
        url=f"/media/{session_id}/{filename}",
        consented=True,
    )
    s.visual_assets = [item for item in s.visual_assets if item.id != record.id] + [record]
    save_session(s)
    return record.model_dump()


@app.post("/api/sessions/{session_id}/visual-episode/plan")
async def create_visual_plan(
    session_id: str,
    portrait_consent: bool = False,
    live_video_consent: bool = False,
    episode_number: int | None = None,
):
    s = load_session(session_id)
    if s and s.preferences.output_mode != "video":
        raise HTTPException(409, "Audio series does not create a visual episode")
    if s and not _has_two_series_videos(s):
        raise HTTPException(409, "Upload both source videos before planning the video episode")
    active_number = episode_number or (s.active_episode_number if s else 1)
    active_episode = _series_episode(s, active_number) if s and s.episodes else None
    if episode_number is not None and s and s.episodes and not active_episode:
        raise HTTPException(404, "Episode not found")
    script = active_episode.production_script if active_episode else (s.production_script if s else None)
    if not s or not s.creative_dna or not script:
        raise HTTPException(400, "Generate the approved production script before planning visuals")
    target_duration = round(active_episode.actual_duration_seconds or script.estimated_duration_seconds or 90)
    plan = await plan_visual_episode(
        s.creative_dna,
        script,
        _series_video_assets(s),
        target_duration_seconds=target_duration,
    )
    plan.portrait_consent = False
    plan.live_video_consent = True
    s.visual_episode_plan = plan
    s.visual_episode = VisualEpisodeResult(
        status="planned",
        message=f"Video plan synced to the {target_duration}-second audio master.",
        duration_seconds=float(target_duration),
    )
    if active_episode:
        s.active_episode_number = active_episode.number
        active_episode.visual_episode_plan = plan
        active_episode.visual_episode = s.visual_episode
    save_session(s)
    await emit(session_id, "visual_director", "artifact", {"visual_episode_plan": plan.model_dump()})
    return plan.model_dump()


async def _finish_video_teaser(session_id: str, episode_number: int | None, video_id: str):
    """Finish the generated scene and package it with the episode's real audio."""
    try:
        job, content = await wait_for_video_teaser(video_id)
        s = load_session(session_id)
        if not s:
            return
        episode = _series_episode(s, episode_number) if episode_number and s.episodes else None
        filename = f"episode-{episode.number}-scene.mp4" if episode else "story-scene.mp4"
        destination = SESSIONS_DIR / session_id / "visual" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        episode_video = _compose_episode_video(session_id, episode, destination)
        result = VisualEpisodeResult(
            status="ready", url=(f"/media/{session_id}/{episode_video.name}" if episode_video else f"/media/{session_id}/{filename}"),
            message=("Your full episode video is ready." if episode_video else "Your generated episode scene is ready."), provider_job_id=video_id,
            progress=int(job.get("progress") or 100),
            duration_seconds=float(episode.actual_duration_seconds) if episode and episode.actual_duration_seconds else None,
        )
    except Exception as exc:
        log.warning("Video teaser failed for %s: %s", session_id, exc)
        s = load_session(session_id)
        if not s:
            return
        episode = _series_episode(s, episode_number) if episode_number and s.episodes else None
        result = VisualEpisodeResult(status="failed", message=str(exc), provider_job_id=video_id)
    s.visual_episode = result
    if episode:
        episode.visual_episode = result
    save_session(s)
    await emit(session_id, "visual_director", "artifact", {
        "episode_number": episode_number,
        "visual_episode": result.model_dump(),
    })


@app.post("/api/sessions/{session_id}/visual-episode/render")
async def render_video_teaser(
    session_id: str,
    background_tasks: BackgroundTasks,
    episode_number: int | None = None,
):
    """Make one creator-confirmed visual episode, never an automatic provider spend."""
    s = load_session(session_id)
    if not s or not s.creative_dna:
        raise HTTPException(404, "Session not found")
    if s.preferences.output_mode != "video":
        raise HTTPException(409, "Audio series does not create video")
    if not _has_two_series_videos(s):
        raise HTTPException(409, "Upload both source videos before creating the video episode")
    active_number = episode_number or s.active_episode_number
    episode = _series_episode(s, active_number) if s.episodes else None
    if episode_number is not None and not episode:
        raise HTTPException(404, "Episode not found")
    plan = episode.visual_episode_plan if episode else s.visual_episode_plan
    current = episode.visual_episode if episode else s.visual_episode
    if not plan:
        raise HTTPException(409, "Plan the visual version before making a teaser")
    if current and current.status == "rendering":
        raise HTTPException(409, "A teaser is already rendering")

    # A video-series episode is an editorial cut of the two supplied videos,
    # with the approved audio as the timing master. It is deterministic, uses
    # both source files, and stays exactly as long as the audio episode.
    uploaded_video = _compose_uploaded_video_episode(session_id, episode)
    if s.preferences.output_mode == "video" and not uploaded_video:
        raise HTTPException(503, "The two source videos could not be cut to the audio master")
    if uploaded_video and episode:
        result = VisualEpisodeResult(
            status="ready",
            url=f"/media/{session_id}/{uploaded_video.name}",
            message=f"Your two source videos are cut to the {round(episode.actual_duration_seconds or 90)}-second audio master.",
            duration_seconds=float(episode.actual_duration_seconds or 90),
            progress=100,
        )
        s.visual_episode = result
        s.active_episode_number = episode.number
        episode.visual_episode = result
        save_session(s)
        await emit(session_id, "visual_director", "artifact", {
            "episode_number": episode.number,
            "visual_episode": result.model_dump(),
        })
        return result.model_dump()
    try:
        reference = _prepared_place_reference(session_id, s.visual_assets, episode.number if episode else None)
        job = await start_video_teaser(s.creative_dna, plan, reference)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    result = VisualEpisodeResult(
        status="rendering", message="Building your audio-synced episode video from its story scene.",
        provider_job_id=job["id"], progress=int(job.get("progress") or 0),
    )
    s.visual_episode = result
    if episode:
        s.active_episode_number = episode.number
        episode.visual_episode = result
    save_session(s)
    background_tasks.add_task(_finish_video_teaser, session_id, episode.number if episode else None, job["id"])
    await emit(session_id, "visual_director", "artifact", {
        "episode_number": episode.number if episode else None,
        "visual_episode": result.model_dump(),
    })
    return result.model_dump()


@app.post("/api/sessions/{session_id}/visual-episode/compose")
async def compose_existing_episode_video(session_id: str, episode_number: int | None = None):
    """Turn an already-completed generated scene into its full episode video without another provider call."""
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    episode = _series_episode(s, episode_number or s.active_episode_number) if s.episodes else None
    result = episode.visual_episode if episode else s.visual_episode
    if not result or not result.url:
        raise HTTPException(409, "Create the visual scene before packaging the episode video")
    source = SESSIONS_DIR / session_id / "visual" / Path(result.url).name
    output = _compose_episode_video(session_id, episode, source)
    if not output:
        raise HTTPException(409, "The episode audio and scene are needed before packaging the video")
    result.status = "ready"
    result.url = f"/media/{session_id}/{output.name}"
    result.message = "Your full episode video is ready."
    s.visual_episode = result
    if episode:
        episode.visual_episode = result
    save_session(s)
    await emit(session_id, "visual_director", "artifact", {"visual_episode": result.model_dump()})
    return result.model_dump()


@app.get("/media/{session_id}/{filename}")
async def serve_media(session_id: str, filename: str):
    session_id = _validated_session_id(session_id)
    filename = _validated_filename(filename)
    path = SESSIONS_DIR / session_id / "visual" / filename
    if not path.exists():
        raise HTTPException(404, "Media not found")
    return FileResponse(str(path))


# ─── Audio file serving ───────────────────────────────────────────────────────

@app.get("/audio/{session_id}/{filename}")
async def serve_audio(session_id: str, filename: str):
    session_id = _validated_session_id(session_id)
    filename = _validated_filename(filename)
    path = SESSIONS_DIR / session_id / "audio" / filename
    if not path.exists():
        # Try session root
        path = SESSIONS_DIR / session_id / filename
    if not path.exists():
        raise HTTPException(404, "Audio not found")
    return FileResponse(str(path), media_type="audio/mpeg")


# ─── Artifacts ────────────────────────────────────────────────────────────────

@app.get("/api/sessions/{session_id}/artifacts")
async def get_artifacts(session_id: str):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404)
    return s.model_dump()
