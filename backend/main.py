"""
Nolan — FastAPI backend
All endpoints, SSE streaming, file serving.
"""
from __future__ import annotations
import ssl_noverify  # noqa: F401 — must be first: disables SSL verify for corporate proxy
import asyncio, json, os, uuid, io
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from schemas import (
    Session, WorkflowStatus, CreativeDNA, VisionSelection,
    ChangeRequest, VoiceCameoConsent,
)
from workflow import (
    load_session, save_session, update_status, get_queue,
    run_transcription, run_dna_extraction,
    run_produce_workflow, run_revision_workflow,
    SESSIONS_DIR,
)
from agents.voice_cameo import clone_voice, preview_cameo, delete_cameo
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("nolan.main")

NOLAN_MODE = os.getenv("NOLAN_MODE", "hybrid")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
AUDIO_DIR = SESSIONS_DIR


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
async def submit_idea_audio(session_id: str, audio: UploadFile = File(...)):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")

    audio_bytes = await audio.read()
    transcript = await run_transcription(session_id, audio_bytes)

    s.transcript = transcript
    update_status(s, WorkflowStatus.TRANSCRIBED)
    return {"transcript": transcript}


# ─── Creative DNA ─────────────────────────────────────────────────────────────

class TranscriptBody(BaseModel):
    transcript: str

@app.post("/api/sessions/{session_id}/extract-dna")
async def extract_dna_endpoint(session_id: str, body: TranscriptBody):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")

    s.transcript = body.transcript
    dna = await run_dna_extraction(session_id, body.transcript)
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


# ─── Visions + Produce ────────────────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/generate-visions")
async def generate_visions_endpoint(session_id: str, background_tasks: BackgroundTasks):
    s = load_session(session_id)
    if not s or not s.creative_dna:
        raise HTTPException(400, "DNA not extracted yet")

    async def _run():
        from workflow import run_vision_generation, emit, close_stream
        visions = await run_vision_generation(session_id, s.creative_dna)
        s.visions = visions
        update_status(s, WorkflowStatus.VISIONS_READY)
        await emit(session_id, "writer", "complete", {"visions_count": len(visions)})
        await close_stream(session_id)

    background_tasks.add_task(_run)
    return {"status": "generating"}


class SelectionBody(BaseModel):
    vision_selection: VisionSelection

@app.post("/api/sessions/{session_id}/produce")
async def produce(session_id: str, body: SelectionBody, background_tasks: BackgroundTasks):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")

    s.selected_vision = body.vision_selection
    update_status(s, WorkflowStatus.VISION_SELECTED)
    background_tasks.add_task(run_produce_workflow, session_id)
    return {"status": "producing"}


# ─── Revision (Semantic Creative Lock) ───────────────────────────────────────

class ReviseBody(BaseModel):
    change_request: ChangeRequest

@app.post("/api/sessions/{session_id}/revise")
async def revise(session_id: str, body: ReviseBody, background_tasks: BackgroundTasks):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
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

@app.post("/api/sessions/{session_id}/voice-cameo/clone")
async def voice_cameo_clone(session_id: str, audio: UploadFile = File(...)):
    s = load_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")

    audio_bytes = await audio.read()
    voice_id, requires_verification = await clone_voice(audio_bytes, session_id)

    if not voice_id:
        return {"success": False, "message": "Voice cloning failed — using stock voice"}

    if requires_verification:
        return {"success": False, "requires_verification": True,
                "message": "ElevenLabs requires manual verification for this voice"}

    # Store voice_id temporarily in session
    from schemas import VoiceCameoResult
    s.voice_cameo = VoiceCameoResult(
        voice_id=voice_id,
        assigned_to="character",
        character_name="KARAN",
        preview_text="I see you, Maya. I am the only one who does.",
    )
    save_session(s)

    # Generate preview
    preview_bytes = await preview_cameo(voice_id)
    preview_path = SESSIONS_DIR / session_id / "cameo_preview.mp3"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(preview_bytes)

    return {"success": True, "voice_id": voice_id, "preview_url": f"/audio/{session_id}/cameo_preview.mp3"}


@app.delete("/api/sessions/{session_id}/voice-cameo")
async def delete_voice_cameo(session_id: str):
    s = load_session(session_id)
    if not s or not s.voice_cameo:
        return {"status": "no cameo to delete"}
    await delete_cameo(s.voice_cameo.voice_id)
    s.voice_cameo = None
    save_session(s)
    return {"status": "deleted"}


# ─── Audio file serving ───────────────────────────────────────────────────────

@app.get("/audio/{session_id}/{filename}")
async def serve_audio(session_id: str, filename: str):
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
