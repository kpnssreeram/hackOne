"""
Nolan — FastAPI backend
All endpoints, SSE streaming, file serving.
"""
from __future__ import annotations
import asyncio, json, os, uuid, io
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from schemas import (
    Session, WorkflowStatus, CreativeDNA, VisionSelection,
    ChangeRequest, EpisodeFeedback, EpisodeStatus, VoiceCameoConsent,
    SessionPreferences, VisualAsset,
)
from workflow import (
    load_session, save_session, update_status, get_queue,
    run_transcription, run_dna_extraction,
    run_confirmed_episode_render, run_continue_series, run_episode_draft,
    run_episode_revision, run_produce_workflow, run_revision_workflow,
    run_series_outline, run_audio_render,
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
async def create_cover_image(session_id: str, episode_number: int | None = None):
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

    image_bytes = await generate_episode_cover(s.creative_dna, script)
    stem = f"episode-{active_episode.number}-cover" if active_episode else "episode-cover"
    filename = f"{stem}.png" if image_bytes else f"{stem}.svg"
    content = image_bytes or fallback_cover_svg(s.creative_dna, script)
    destination = SESSIONS_DIR / session_id / "visual" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)

    url = f"/media/{session_id}/{filename}"
    s.cover_image_url = url
    if active_episode:
        s.active_episode_number = active_episode.number
        active_episode.cover_image_url = url
    save_session(s)
    await emit(session_id, "visual_director", "artifact", {
        "cover_image_url": url,
        "generated": bool(image_bytes),
    })
    return {"url": url, "generated": bool(image_bytes)}


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
    active_number = episode_number or (s.active_episode_number if s else 1)
    active_episode = _series_episode(s, active_number) if s and s.episodes else None
    if episode_number is not None and s and s.episodes and not active_episode:
        raise HTTPException(404, "Episode not found")
    script = active_episode.production_script if active_episode else (s.production_script if s else None)
    if not s or not s.creative_dna or not script:
        raise HTTPException(400, "Generate the approved production script before planning visuals")
    plan = await plan_visual_episode(s.creative_dna, script, s.visual_assets)
    plan.portrait_consent = portrait_consent or any(asset.kind == "photo" and asset.consented for asset in s.visual_assets)
    plan.live_video_consent = live_video_consent or any(asset.kind == "video" and asset.consented for asset in s.visual_assets)
    s.visual_episode_plan = plan
    s.visual_episode = VisualEpisodeResult(status="planned", message="Visual episode is planned. Your clips and photos stay original; place references guide the edit without generating a real person.")
    if active_episode:
        s.active_episode_number = active_episode.number
        active_episode.visual_episode_plan = plan
        active_episode.visual_episode = s.visual_episode
    save_session(s)
    await emit(session_id, "visual_director", "artifact", {"visual_episode_plan": plan.model_dump()})
    return plan.model_dump()


async def _finish_video_teaser(session_id: str, episode_number: int | None, video_id: str):
    """Finish a provider render after the fast API response has returned."""
    try:
        job, content = await wait_for_video_teaser(video_id)
        s = load_session(session_id)
        if not s:
            return
        episode = _series_episode(s, episode_number) if episode_number and s.episodes else None
        filename = f"episode-{episode.number}-teaser.mp4" if episode else "story-teaser.mp4"
        destination = SESSIONS_DIR / session_id / "visual" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        result = VisualEpisodeResult(
            status="ready", url=f"/media/{session_id}/{filename}",
            message="Your 20-second story teaser is ready.", provider_job_id=video_id,
            progress=int(job.get("progress") or 100),
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
    """Make one creator-confirmed 20-second teaser, never an automatic full video."""
    s = load_session(session_id)
    if not s or not s.creative_dna:
        raise HTTPException(404, "Session not found")
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
    try:
        job = await start_video_teaser(s.creative_dna, plan)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    result = VisualEpisodeResult(
        status="rendering", message="Making your 20-second story teaser.",
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
