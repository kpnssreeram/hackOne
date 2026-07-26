"""
All Pydantic schemas for Nolan.
Every agent input/output is typed. No untyped dicts in the pipeline.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator
from enum import Enum


# ─── Workflow ────────────────────────────────────────────────────────────────

class WorkflowStatus(str, Enum):
    CAPTURED           = "CAPTURED"
    TRANSCRIBED        = "TRANSCRIBED"
    DNA_EXTRACTED      = "DNA_EXTRACTED"
    VISION_GENERATING  = "VISION_GENERATING"
    VISIONS_READY      = "VISIONS_READY"
    VISION_SELECTED    = "VISION_SELECTED"
    SCRIPT_DRAFTED     = "SCRIPT_DRAFTED"
    CONSTITUTION_DONE  = "CONSTITUTION_DONE"
    AUDIO_RENDERING    = "AUDIO_RENDERING"
    AUDIO_RENDERED     = "AUDIO_RENDERED"
    READY              = "READY"
    CHANGE_ANALYZED    = "CHANGE_ANALYZED"
    REVISING           = "REVISING"
    SCENES_REWRITTEN   = "SCENES_REWRITTEN"
    DEGRADED           = "DEGRADED"
    ERROR              = "ERROR"


class EpisodeStatus(str, Enum):
    """A small, confirmation-first lifecycle for one episode in a three-part story."""
    OUTLINED = "OUTLINED"
    DRAFTING = "DRAFTING"
    DRAFT_READY = "DRAFT_READY"
    RENDERING = "RENDERING"
    READY = "READY"
    APPROVED = "APPROVED"
    REVISING = "REVISING"
    STALE = "STALE"


# ─── Creative DNA ────────────────────────────────────────────────────────────

class Protagonist(BaseModel):
    name: str
    desire: str
    fear: str

class StoryCharacter(BaseModel):
    name: str
    role: str
    relationship_to_protagonist: str
    want: str
    secret_or_tension: str

class CreativeDNA(BaseModel):
    core_emotion: str
    audience_promise: str
    protagonist: Protagonist
    central_conflict: str
    symbols: list[str]
    non_negotiables: list[str]
    tone: list[str]
    genre: list[str] = []
    story_references: list[str] = []
    characters: list[StoryCharacter] = []
    premise: str = ""
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
    preserve_elements: list[str] = Field(default_factory=list)


class ChangedProductionLine(BaseModel):
    """A surgical replacement for one line in a production script."""
    line_index: int = Field(ge=0)
    line: ProductionLine

class CreativeLockDiff(BaseModel):
    change_request: str
    affected_scene_ids: list[str] = Field(default_factory=list)
    preserved_elements: list[str] = Field(default_factory=list)
    locked_elements: list[str] = Field(default_factory=list)
    # Kept for the richer replay artifact and backwards-compatible clients.
    changed_scenes: list[Scene] = Field(default_factory=list)
    impact_summary: Optional[str] = None
    # Live revisions use exact indexes so the rendered audio matches the diff.
    changed_lines: list[ChangedProductionLine] = Field(default_factory=list)


# ─── Voice Cameo ─────────────────────────────────────────────────────────────

class VoiceCameoConsent(BaseModel):
    confirmed: bool
    assigned_to: Literal["narrator", "character"]
    character_name: Optional[str] = None

class SessionPreferences(BaseModel):
    """Creator-controlled settings. Never infer a person's gender from audio."""
    output_language: str = Field(default="auto", max_length=48)
    # Character name -> either ``auto:<presentation>`` or ``voice:<ElevenLabs
    # voice id>``. Legacy feminine/masculine/neutral values remain accepted.
    voice_cast: dict[str, str] = Field(default_factory=dict)

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
    provider_job_id: Optional[str] = None
    progress: Optional[int] = None


# ─── Three-Episode Story ─────────────────────────────────────────────────────

class EpisodeOutline(BaseModel):
    number: int = Field(ge=1, le=3)
    title: str
    what_happens: str
    emotional_turn: str
    ending_promise: str


class SeriesPlan(BaseModel):
    title: str
    logline: str
    tone: str
    ending_promise: str
    episode_outlines: list[EpisodeOutline] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def has_one_outline_for_each_episode(self) -> "SeriesPlan":
        """Prevent an apparently complete plan from losing an episode to duplicate IDs."""
        if [outline.number for outline in self.episode_outlines] != [1, 2, 3]:
            raise ValueError("episode_outlines must contain episodes 1, 2, and 3 in order")
        return self


class EpisodeFeedback(BaseModel):
    """Plain-language creator feedback collected after one completed episode."""
    keep: str = ""
    change_this_episode: str = ""
    next_direction: str = ""


class VisualAsset(BaseModel):
    """Creator-provided media that can be placed in an episode without regeneration."""
    id: str
    kind: Literal["photo", "video", "place_reference"]
    filename: str
    url: str
    consented: bool = False


class StoryEpisode(BaseModel):
    number: int = Field(ge=1, le=3)
    outline: EpisodeOutline
    status: EpisodeStatus = EpisodeStatus.OUTLINED
    production_script: Optional[ProductionScript] = None
    constitution_report: Optional[ConstitutionReport] = None
    feedback: Optional[EpisodeFeedback] = None
    continuity_summary: Optional[str] = None
    audio_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    actual_duration_seconds: Optional[float] = None
    visual_episode_plan: Optional[VisualEpisodePlan] = None
    visual_episode: Optional[VisualEpisodeResult] = None

    @model_validator(mode="after")
    def outline_matches_episode_number(self) -> "StoryEpisode":
        if self.outline.number != self.number:
            raise ValueError("episode number must match its outline number")
        return self


# ─── Session ─────────────────────────────────────────────────────────────────

class Session(BaseModel):
    id: str
    status: WorkflowStatus = WorkflowStatus.CAPTURED
    mode: Literal["live", "hybrid", "replay"] = "hybrid"
    transcript: Optional[str] = None
    detected_input_language: Optional[str] = None
    preferences: SessionPreferences = Field(default_factory=SessionPreferences)
    creative_dna: Optional[CreativeDNA] = None
    visions: Optional[list[VisionCard]] = None
    selected_vision: Optional[VisionSelection] = None
    scene_graph: Optional[NarrativeSceneGraph] = None
    production_script: Optional[ProductionScript] = None
    constitution_report: Optional[ConstitutionReport] = None
    creative_lock_diff: Optional[CreativeLockDiff] = None
    audio_url: Optional[str] = None
    cover_image_url: Optional[str] = None
    visual_episode_plan: Optional[VisualEpisodePlan] = None
    visual_episode: Optional[VisualEpisodeResult] = None
    # The complete story is planned at once, but costly media is created only
    # after the creator confirms each individual episode.
    series_plan: Optional[SeriesPlan] = None
    episodes: list[StoryEpisode] = Field(default_factory=list)
    active_episode_number: int = Field(default=1, ge=1, le=3)
    visual_assets: list[VisualAsset] = Field(default_factory=list)
    voice_cameo: Optional[VoiceCameoResult] = None
    voice_cameo_consent: Optional[VoiceCameoConsent] = None
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
