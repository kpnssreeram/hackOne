"""
Precomputed golden-path fixtures for the demo scenario.
Used by HYBRID and REPLAY modes, and as circuit-breaker fallbacks.

Scenario: "I dreamed the entire world forgot me, but my dead brother kept
           calling my phone. Make it mysterious and emotional."
"""
from __future__ import annotations
from schemas import (
    CreativeDNA, Protagonist, StoryCharacter, VisionCard, VisionSelection,
    NarrativeSceneGraph, Character, Relationship, Scene,
    DialogueLine, AudioCue, ProductionScript, ProductionLine,
    ConstitutionReport, ConstitutionCheck, CreativeLockDiff,
)

# ─── Transcript ───────────────────────────────────────────────────────────────

FIXTURE_TRANSCRIPT = (
    "I dreamed the entire world forgot me, but my dead brother kept calling "
    "my phone. Make it mysterious and emotional."
)

# ─── Creative DNA ─────────────────────────────────────────────────────────────

FIXTURE_DNA = CreativeDNA(
    core_emotion="fear of erasure from existence",
    audience_promise="discover why death remembers what life forgets",
    protagonist=Protagonist(
        name="Maya",
        desire="prove she is still real — that she existed",
        fear="complete erasure from every living memory",
    ),
    central_conflict="The world has deleted Maya from its memory, but her dead brother's phone keeps calling her",
    symbols=["silent contact list", "cracked phone screen", "old voicemail", "empty hospital bed"],
    non_negotiables=["dead brother is the only one who remembers Maya", "mystery of why must remain unresolved at episode end"],
    tone=["mysterious", "emotional", "haunting"],
    genre=["supernatural mystery", "emotional drama"],
    story_references=["slow-burn mystery", "relationship-driven horror"],
    characters=[
        StoryCharacter(
            name="Karan", role="brother",
            relationship_to_protagonist="Maya's dead brother — the only one who remembers",
            want="reach Maya before she disappears entirely",
            secret_or_tension="his calls may not be coming from where she thinks",
        ),
        StoryCharacter(
            name="Priya", role="best friend",
            relationship_to_protagonist="childhood best friend who no longer recognises Maya",
            want="to feel like something is missing but cannot name it",
            secret_or_tension="she was the last person to see Karan alive",
        ),
    ],
    premise="Maya has been erased from the living world, but her dead brother Karan keeps calling her phone — the only proof she ever existed.",
    creative_freedom=68,
    locked_fields=[],
)

# ─── Vision Cards ─────────────────────────────────────────────────────────────

FIXTURE_VISIONS = [
    VisionCard(
        id="fractured_time",
        title="Fractured Time",
        grammar="Nonlinear revelation — the audience knows the answer before Maya does",
        premise="Maya wakes mid-erasure and must race backward through her own fading timeline to find the moment it began",
        opening_preview=(
            "[SFX: hospital heart monitor flatlines]\n"
            "NARRATOR: This is the story of a woman the world decided to forget.\n"
            "[SILENCE: 1.2s]\n"
            "MAYA [gasping]: My name is Maya. My name is Maya. Someone please—\n"
            "[SFX: phone vibrates, unknown caller]\n"
            "BROTHER [distorted voicemail]: I remember you. Don't stop fighting."
        ),
        emotional_trajectory="Disorientation → dread → desperate hope → haunting revelation",
        cliffhanger_type="Temporal — the final call arrives before the brother's death, not after",
        constitution_score=91,
        why_it_fits_dna="Fractured structure mirrors the core emotion of fractured identity. The mystery of why only the dead remember becomes the structural engine.",
    ),
    VisionCard(
        id="emotional_intimacy",
        title="Emotional Intimacy",
        grammar="Relationship-first — silence and restraint carry more weight than action",
        premise="Maya spends one night retracing every place she and her brother shared, while the city grows colder and emptier around her",
        opening_preview=(
            "[AMBIENCE: empty railway platform, distant rain]\n"
            "[SILENCE: 1.8s]\n"
            "MAYA [quietly]: Everyone forgot me today. My boss. My friends. Even my mother.\n"
            "[SILENCE: 0.9s]\n"
            "MAYA: But you called.\n"
            "[SFX: voicemail notification]\n"
            "BROTHER [warm, distant]: Hey. Just checking in. You okay?"
        ),
        emotional_trajectory="Quiet grief → fragile connection → devastating tenderness → open wound",
        cliffhanger_type="Emotional — Maya realizes the voicemail was recorded six months before his death",
        constitution_score=87,
        why_it_fits_dna="The intimacy grammar gives space for the core emotion to breathe. The brother's voice becomes the only anchor in a world erasing her.",
    ),
    VisionCard(
        id="kinetic_mystery",
        title="Kinetic Mystery",
        grammar="Immediate danger — short scenes, reversal every 90 seconds, no safe moments",
        premise="Maya has 24 hours before she disappears entirely. She must find her brother's phone before the calls stop",
        opening_preview=(
            "[SFX: running footsteps on concrete]\n"
            "MAYA [breathless]: The door — it won't open. My keycard says I don't exist.\n"
            "[SFX: phone rings — unknown number]\n"
            "MAYA: Hello?\n"
            "BROTHER [echo, fragmented]: Find. The. Phone.\n"
            "[SFX: connection drops]\n"
            "MAYA: Karan? KARAN?"
        ),
        emotional_trajectory="Panic → grim focus → shocking reversal → breathless cliffhanger",
        cliffhanger_type="Physical — Maya finds the phone. The last call was made tonight. Her brother died two years ago.",
        constitution_score=89,
        why_it_fits_dna="Kinetic structure externalises the internal terror of erasure. The race to find the phone gives the audience a clear dramatic question with immediate stakes.",
    ),
]

# ─── Production Script ────────────────────────────────────────────────────────

FIXTURE_PRODUCTION_SCRIPT = ProductionScript(
    title="The Last Caller — Pilot",
    estimated_duration_seconds=75,
    lines=[
        ProductionLine(type="ambience", description="Empty railway platform, distant rain, low wind", duration_seconds=2.5),
        ProductionLine(type="silence", duration_seconds=1.8),
        ProductionLine(type="dialogue", character="MAYA", text="Everyone forgot me today.", emotion="quiet devastation", voice_note="barely above a whisper"),
        ProductionLine(type="silence", duration_seconds=0.9),
        ProductionLine(type="dialogue", character="MAYA", text="My boss looked through me. My friends — they didn't even blink when I left. And my mother...", emotion="numb", voice_note="trailing off"),
        ProductionLine(type="silence", duration_seconds=0.6),
        ProductionLine(type="dialogue", character="MAYA", text="She asked who I was.", emotion="breaking", voice_note="barely held together"),
        ProductionLine(type="sfx", description="Phone vibrates on a metal bench — three pulses", duration_seconds=1.5),
        ProductionLine(type="silence", duration_seconds=0.8),
        ProductionLine(type="dialogue", character="MAYA", text="Unknown number.", emotion="wary"),
        ProductionLine(type="sfx", description="Voicemail notification chime", duration_seconds=0.5),
        ProductionLine(type="silence", duration_seconds=0.4),
        ProductionLine(type="dialogue", character="KARAN", text="Hey. It's Karan. Just... checking in. Are you okay?", emotion="warm, impossibly familiar", voice_note="voicemail distortion filter, gentle"),
        ProductionLine(type="silence", duration_seconds=1.5),
        ProductionLine(type="dialogue", character="MAYA", text="Karan has been dead for two years.", emotion="hollow shock", voice_note="to herself"),
        ProductionLine(type="sfx", description="Wind picks up sharply on the platform", duration_seconds=1.0),
        ProductionLine(type="dialogue", character="MAYA", text="But he called.", emotion="desperate wonder"),
        ProductionLine(type="silence", duration_seconds=0.7),
        ProductionLine(type="dialogue", character="MAYA", text="He called, and he knew my name.", emotion="raw, breaking open"),
        ProductionLine(type="music", description="Low sustained strings — single unresolved chord — fade in", duration_seconds=4.0),
        ProductionLine(type="silence", duration_seconds=1.2),
        ProductionLine(type="dialogue", character="NARRATOR", text="The Last Caller. Episode One: I Remember You.", emotion="measured, quiet authority"),
        ProductionLine(type="music", description="Strings swell then cut", duration_seconds=2.0),
    ],
)

# ─── Constitution Report ──────────────────────────────────────────────────────

FIXTURE_CONSTITUTION = ConstitutionReport(
    overall_score=88,
    checks=[
        ConstitutionCheck(rule_number=1, rule="Hook within 15 seconds", passed=True,
            evidence="Ambience + silence + first Maya line establishes mood in ~5 seconds. Dramatic question (everyone forgot her) lands by line 2.", reason=None, repair=None),
        ConstitutionCheck(rule_number=2, rule="Understandable without visuals", passed=True,
            evidence="All actions are conveyed through sound (phone vibrates on metal) or dialogue. No visual-only blocking.", reason=None, repair=None),
        ConstitutionCheck(rule_number=3, rule="Conflict escalates within pilot", passed=True,
            evidence="Escalation: world forgets → mother forgets → dead brother calls. Each beat raises the stakes.", reason=None, repair=None),
        ConstitutionCheck(rule_number=4, rule="Character motivation preserved", passed=True,
            evidence="Maya's desire (to be remembered) and fear (erasure) are both present in her dialogue choices.", reason=None, repair=None),
        ConstitutionCheck(rule_number=5, rule="Sound purpose", passed=True,
            evidence="Rain = isolation. Phone vibration = inciting event. Voicemail chime = supernatural intrusion. Wind = world responding to the break.", reason=None, repair=None),
        ConstitutionCheck(rule_number=6, rule="Narration economy", passed=False,
            evidence="Line: 'Everyone forgot me today. My boss looked through me.' — this is telling, not showing.",
            reason="A line of internal narration replaces what could be a stronger, more audio-native beat.",
            repair="[SFX: office ambient noise fades — phone ringing stops when Maya answers]\nBOSS [cheerful, to someone else]: Great! So as I was saying to David—\nMAYA: ...I'm standing right here.\n[SILENCE: 1.0s]\nBOSS [confused]: Sorry, can I help you?"),
        ConstitutionCheck(rule_number=7, rule="Ends on unresolved consequential moment", passed=True,
            evidence="Dead brother called. He knew her name. The episode ends on that impossible fact with a question the audience must return to answer.", reason=None, repair=None),
        ConstitutionCheck(rule_number=8, rule="Creative DNA preserved", passed=True,
            evidence="Core emotion (erasure), non-negotiable (brother remembers), tone (mysterious, haunting) all present.", reason=None, repair=None),
    ],
    repaired_script_patch=(
        "REPLACE scene-1 narration block with:\n"
        "[SFX: office ambient noise — phones, keyboards]\n"
        "BOSS [warm, to someone else]: Great presentation, David. Really.\n"
        "MAYA: I gave that presentation.\n"
        "[SILENCE: 0.8s]\n"
        "BOSS [confused]: Sorry — do I know you?"
    ),
)

# ─── Revision Diff (Semantic Creative Lock) ───────────────────────────────────

FIXTURE_REVISION_DIFF = CreativeLockDiff(
    change_request="Make the brother dangerous instead of protective, but preserve the final reveal",
    affected_scene_ids=["scene-voicemail", "scene-revelation"],
    preserved_elements=[
        "Final reveal: brother called tonight but died two years ago",
        "Core emotion: Maya's fear of erasure",
        "Maya's name: Maya",
        "Cliffhanger: impossible phone call"
    ],
    locked_elements=[
        "Final two lines of episode",
        "Creative DNA: core_emotion, non_negotiables",
        "Karan's name",
    ],
    changed_scenes=[
        Scene(
            id="scene-voicemail",
            time="present",
            location="empty railway platform",
            characters=["maya", "karan"],
            purpose="Establish the call — but now the tone is a threat, not comfort",
            knowledge_before=[],
            knowledge_after=["karan-called", "karan-sounds-wrong"],
            setup_ids=["broken-contacts"],
            payoff_ids=["final-reveal"],
            locked=False,
            dialogue=[
                DialogueLine(character="KARAN", text="I see you, Maya. I am the only one who does.", emotion="cold, deliberate", voice_note="voicemail distortion — lower, slower", sfx_before="phone vibrates — five long pulses"),
                DialogueLine(character="MAYA", text="Karan? What's wrong with your voice?", emotion="alarmed", pause_after_seconds=0.5),
                DialogueLine(character="KARAN", text="Come find the phone. Before someone else does.", emotion="flat warning", sfx_after="call drops — hard cut to silence"),
            ]
        )
    ],
    # Keep replay revision honest: these indexes replace the actual pilot
    # lines, rather than merely showing a scene diff before rendering the old
    # audio again.
    changed_lines=[
        {
            "line_index": 12,
            "line": {
                "type": "dialogue", "character": "KARAN",
                "text": "I see you, Maya. I am the only one who does.",
                "emotion": "cold, deliberate",
                "voice_note": "voicemail distortion — lower, slower",
            },
        },
        {
            "line_index": 14,
            "line": {
                "type": "dialogue", "character": "MAYA",
                "text": "Karan? What's wrong with your voice?",
                "emotion": "alarmed",
            },
        },
        {
            "line_index": 16,
            "line": {
                "type": "dialogue", "character": "KARAN",
                "text": "Come find the phone. Before someone else does.",
                "emotion": "flat warning",
                "voice_note": "hard, threatening stillness",
            },
        },
    ],
)

# ─── Voice Cameo sample text ──────────────────────────────────────────────────

VOICE_CAMEO_ENROLLMENT_TEXT = (
    "In this moment, I am speaking clearly and at a natural pace. "
    "My name does not matter. What matters is the story. "
    "I am recording this so that my voice can become part of something greater — "
    "a mystery, a dream, a memory that refuses to fade. "
    "The rain falls on the platform. The phone vibrates. And somewhere, "
    "a voice that should not exist says: I remember you."
)

VOICE_CAMEO_PREVIEW_LINE = "I see you, Maya. I am the only one who does."


def get_fixture(stage: str) -> dict:
    """Return fixture data for a given stage. Used by circuit breaker fallback."""
    return {
        "transcribe":   {"transcript": FIXTURE_TRANSCRIPT},
        "dna":          FIXTURE_DNA.model_dump(),
        "visions":      [v.model_dump() for v in FIXTURE_VISIONS],
        "script":       FIXTURE_PRODUCTION_SCRIPT.model_dump(),
        "constitution": FIXTURE_CONSTITUTION.model_dump(),
        "revision":     FIXTURE_REVISION_DIFF.model_dump(),
    }.get(stage, {})
