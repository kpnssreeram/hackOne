"""
All Pydantic schemas for Nolan.
Every agent input/output is typed. No untyped dicts in the pipeline.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field
from enum import Enum


# ─── Workflow ────────────────────────────────────────────────────────────────

class WorkflowStatus(str, Enum):
    CAPTURED           = "CAPTURED"
    TRANSCRIBED        = "TRANSCRIBED"
    DNA_EXTRACTED      = "DNA_EXTRACTED"
    VISIONS_READY      = "VISIONS_READY"
    VISION_SELECTED    = "VISION_SELECTED"
    SCRIPT_DRAFTED     = "SCRIPT_DRAFTED"
    CONSTITUTION_DONE  = "CONSTITUTION_DONE"
    AUDIO_RENDERED     = "AUDIO_RENDERED"
    READY              = "READY"
    CHANGE_ANALYZED    = "CHANGE_ANALYZED"
    SCENES_REWRITTEN   = "SCENES_REWRITTEN"
    DEGRADED           = "DEGRADED"
    ERROR              = "ERROR"


# ─── Creative DNA ────────────────────────────────────────────────────────────

class Protagonist(BaseModel):
    name: str
    desire: str
    fear: str

class CreativeDNA(BaseModel):
    core_emotion: str
    audience_promise: str
    protagonist: Protagonist
    central_conflict: str
    symbols: list[str]
    non_negotiables: list[str]
    tone: list[str]
    creative_freedom: int = Field(ge=0, le=100)
    locked_fields: list[str] = []


# ─── Vision Cards ────────────────────────────────────────────────────────────

class VisionCard(BaseModel):
    id: Literal["fractured_time", "emotional_intimacy", "kinetic_mystery"]
    title: str
    grammar: str
    premise: str
    opening_preview: str       # ~15-second script snippet
    emotional_trajectory: str
    cliffhanger_type: str
    constitution_score: int = Field(ge=0, le=100)
    why_it_fits_dna: str


class VisionSelection(BaseModel):
    primary_vision_id: str
    opening_from: str          # vision id
    relationship_from: str     # vision id
    ending_from: str           # vision id
    custom_note: Optional[str] = None


# ─── Narrative Scene Graph ───────────────────────────────────────────────────

class DialogueLine(BaseModel):
    character: str
    text: str
    emotion: str
    voice_note: Optional[str] = None   # e.g. "[whispering]"
    sfx_before: Optional[str] = None   # e.g. "AMBIENCE: rain"
    sfx_after: Optional[str] = None
    pause_after_seconds: float = 0.0

class Scene(BaseModel):
    id: str
    time: str
    location: str
    characters: list[str]
    purpose: str
    knowledge_before: list[str]
    knowledge_after: list[str]
    setup_ids: list[str]
    payoff_ids: list[str]
    locked: bool = False
    dialogue: list[DialogueLine] = []

class Character(BaseModel):
    name: str
    role: str
    voice_id: Optional[str] = None     # ElevenLabs voice_id
    motivation: str
    secret: Optional[str] = None

class Relationship(BaseModel):
    from_char: str
    to_char: str
    nature: str
    known_to_audience: bool

class AudioCue(BaseModel):
    scene_id: str
    cue_type: Literal["ambience", "sfx", "music", "silence"]
    description: str
    duration_seconds: Optional[float] = None

class NarrativeSceneGraph(BaseModel):
    creative_dna: CreativeDNA
    characters: list[Character]
    facts: list[str]
    relationships: list[Relationship]
    scenes: list[Scene]
    unresolved_questions: list[str]
    audio_cues: list[AudioCue]


# ─── Story Constitution ──────────────────────────────────────────────────────

class ConstitutionCheck(BaseModel):
    rule_number: int
    rule: str
    passed: bool
    evidence: str
    reason: Optional[str] = None
    repair: Optional[str] = None       # repaired dialogue/cue if failed

class ConstitutionReport(BaseModel):
    overall_score: int = Field(ge=0, le=100)
    checks: list[ConstitutionCheck]
    repaired_script_patch: Optional[str] = None  # only changed lines


# ─── Production Script ───────────────────────────────────────────────────────

class ProductionLine(BaseModel):
    type: Literal["ambience", "sfx", "silence", "dialogue", "music"]
    character: Optional[str] = None
    text: Optional[str] = None
    emotion: Optional[str] = None
    voice_note: Optional[str] = None
    duration_seconds: Optional[float] = None
    description: Optional[str] = None  # for sfx/ambience

class ProductionScript(BaseModel):
    title: str
    lines: list[ProductionLine]
    estimated_duration_seconds: int


# ─── Creative Lock ────────────────────────────────────────────────────────────

class ChangeRequest(BaseModel):
    change_instruction: str
    preserve_elements: list[str] = []

class CreativeLockDiff(BaseModel):
    change_request: str
    affected_scene_ids: list[str]
    preserved_elements: list[str]
    locked_elements: list[str]
    changed_scenes: list[Scene]


# ─── Voice Cameo ─────────────────────────────────────────────────────────────

class VoiceCameoConsent(BaseModel):
    confirmed: bool
    assigned_to: Literal["narrator", "character"]
    character_name: Optional[str] = None

class VoiceCameoResult(BaseModel):
    voice_id: str
    assigned_to: str
    character_name: Optional[str] = None
    preview_text: str


# ─── Visual Episode ──────────────────────────────────────────────────────────

class VisualBeat(BaseModel):
    id: str
    start_seconds: int = Field(ge=0)
    duration_seconds: int = Field(gt=0, le=20)
    kind: Literal["user_video", "portrait_card", "generated_scene", "title_card"]
    purpose: str
    visual_prompt: str
    narration_anchor: str
    source_asset: Optional[str] = None


class VisualEpisodePlan(BaseModel):
    title: str
    aspect_ratio: Literal["9:16"] = "9:16"
    target_duration_seconds: int = Field(default=90, ge=30, le=90)
    style: str
    protagonist_description: str
    beats: list[VisualBeat]
    portrait_consent: bool = False
    live_video_consent: bool = False


class VisualEpisodeResult(BaseModel):
    status: Literal["planned", "rendering", "ready", "failed"] = "planned"
    url: Optional[str] = None
    message: Optional[str] = None


# ─── Session ─────────────────────────────────────────────────────────────────

class Session(BaseModel):
    id: str
    status: WorkflowStatus = WorkflowStatus.CAPTURED
    mode: Literal["live", "hybrid", "replay"] = "hybrid"
    transcript: Optional[str] = None
    creative_dna: Optional[CreativeDNA] = None
    visions: Optional[list[VisionCard]] = None
    selected_vision: Optional[VisionSelection] = None
    scene_graph: Optional[NarrativeSceneGraph] = None
    production_script: Optional[ProductionScript] = None
    constitution_report: Optional[ConstitutionReport] = None
    creative_lock_diff: Optional[CreativeLockDiff] = None
    audio_url: Optional[str] = None
    visual_episode_plan: Optional[VisualEpisodePlan] = None
    visual_episode: Optional[VisualEpisodeResult] = None
    voice_cameo: Optional[VoiceCameoResult] = None
    is_degraded: bool = False
    degraded_stages: list[str] = []


# ─── API Request/Response ─────────────────────────────────────────────────────

class ProduceRequest(BaseModel):
    creative_dna: CreativeDNA
    vision_selection: VisionSelection

class ReviseRequest(BaseModel):
    change_request: ChangeRequest

class SSEEvent(BaseModel):
    agent: str
    event_type: Literal["token", "artifact", "violation", "repair", "complete", "fallback", "error", "status"]
    data: str | dict
