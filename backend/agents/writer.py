"""
Writer Agent — generates 3 Directorial Visions and the Production Script.
max_retries=0, gpt-4o-mini for speed, robust JSON extraction.
"""
from __future__ import annotations
import os, re, json
from openai import AsyncOpenAI
from schemas import (
    CreativeDNA, EpisodeFeedback, EpisodeOutline, ProductionLine,
    ProductionScript, SeriesPlan, VisionCard, VisionSelection,
)
import logging

log = logging.getLogger("nolan.writer")

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY") or "replay-placeholder", max_retries=0, timeout=38.0)

VISION_SYSTEM = """You are the Writer in Nolan's AI studio.
Generate 3 Directorial Visions — genuinely different narrative grammars.

Grammar types (use EXACTLY these ids):
- "fractured_time": nonlinear, audience knows more than protagonist
- "emotional_intimacy": relationship-first, silence carries weight
- "kinetic_mystery": immediate danger, reversal every 90 seconds

IMPORTANT: Each vision must be SPECIFIC to the user's actual idea — not a generic story.
Use the protagonist's name, their specific symbols, their stated conflict.

Return ONLY a valid JSON array of 3 VisionCard objects. No markdown, no extra text.

VisionCard schema:
{
  "id": "fractured_time" | "emotional_intimacy" | "kinetic_mystery",
  "title": string,
  "grammar": string,
  "premise": string (specific to user's idea),
  "opening_preview": string (15-sec audio script with SFX tags),
  "emotional_trajectory": string,
  "cliffhanger_type": string,
  "constitution_score": number (0-100),
  "why_it_fits_dna": string
}
"""

SCRIPT_SYSTEM = """You are writing a production script for an 80-100 second audio drama episode.

CRITICAL RULES:
1. Every action must be HEARABLE — use [SFX:], [AMBIENCE:], [SILENCE: Xs] tags
2. No visual-only descriptions
3. Use the protagonist's actual name and their specific situation
4. Follow the episode-specific ending instruction exactly
5. Keep dialogue sharp — 1-2 sentences per line max
6. Put performable emotion in `emotion` and `voice_note` fields, e.g. "crying, voice breaking", "whispering", "breathless"
7. Put real audible events in ambience/sfx descriptions: rain, thunder, sobbing, footsteps, doors, phones, crowds, wind
8. If the creator mentions a sound, it must appear as an ambience or sfx line, not only as dialogue text

Return ONLY valid JSON matching ProductionScript schema. No markdown.

Return this exact shape, with no wrapper or `scenes` field:
{"title":"string","estimated_duration_seconds":90,"lines":[{"type":"ambience","description":"string","duration_seconds":2},{"type":"dialogue","character":"NAME","text":"string","emotion":"string"},{"type":"silence","duration_seconds":1},{"type":"sfx","description":"string","duration_seconds":1}]}
Write 18-24 lines, including at least 14 dialogue lines and 230-300 spoken words (or an equivalent amount in the requested language). This must play for 80-100 seconds at a natural voice pace. Do not fake the length with a long ambience tail. Every named character must come from the Creative DNA.
"""

SERIES_SYSTEM = """You are the series writer for Nolan, an emotional audio-story studio.
Create one complete, connected three-episode arc from the creator's Story DNA and chosen treatment.

Episode 1 introduces the world and ends with a consequential unresolved turn.
Episode 2 carries forward the exact unresolved turn, escalates the cost, and ends with a bigger consequential turn.
Episode 3 pays off the central promise with an earned ending; it must not simply stop on a new cliffhanger.

Return only valid JSON matching this exact shape:
{"title":"string","logline":"string","tone":"string","ending_promise":"string","episode_outlines":[
  {"number":1,"title":"string","what_happens":"string","emotional_turn":"string","ending_promise":"string"},
  {"number":2,"title":"string","what_happens":"string","emotional_turn":"string","ending_promise":"string"},
  {"number":3,"title":"string","what_happens":"string","emotional_turn":"string","ending_promise":"string"}
]}
Never invent a new protagonist or discard a Creative DNA non-negotiable."""

OUTPUT_LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi (Devanagari)",
    "te": "Telugu",
    "ta": "Tamil",
    "kn": "Kannada",
    "ml": "Malayalam",
}


def _dialogue_language_instruction(output_language: str | None) -> str:
    """Give the writer a human language name rather than an ISO code."""
    value = (output_language or "auto").strip().lower().replace("_", "-")
    if value == "auto":
        return "Write every dialogue `text` field in the creator's detected input language."
    language = OUTPUT_LANGUAGE_NAMES.get(value.split("-", 1)[0], value)
    return (
        f"Write every dialogue `text` field in {language}. "
        "Do not translate it into English or use transliteration."
    )


def _series_language_instruction(output_language: str | None) -> str:
    value = (output_language or "auto").strip().lower().replace("_", "-")
    if value == "auto":
        return "Write the plan in the creator's input language when it is clear from the story."
    language = OUTPUT_LANGUAGE_NAMES.get(value.split("-", 1)[0], value)
    return f"Write the plan in {language}."


def _fallback_series_plan(dna: CreativeDNA, primary: VisionCard | None = None) -> SeriesPlan:
    """A specific offline/recovery arc, so a provider outage never erases the series promise."""
    name = dna.protagonist.name
    conflict = dna.central_conflict
    symbol = dna.symbols[0] if dna.symbols else "the unanswered signal"
    treatment = primary.title if primary else "Emotional Mystery"
    return SeriesPlan(
        title=f"{name}: {treatment}",
        logline=f"{name} must face {conflict.lower()} before the truth costs too much.",
        tone=", ".join(dna.tone[:3]) or "emotional mystery",
        ending_promise=f"By the end, {name} makes an earned choice about {symbol}.",
        episode_outlines=[
            EpisodeOutline(
                number=1,
                title="The First Sign",
                what_happens=f"{name} discovers the first undeniable sign that {conflict.lower()}.",
                emotional_turn=f"Fear turns into a decision to follow {symbol}.",
                ending_promise="The discovery changes what the audience thinks is possible.",
            ),
            EpisodeOutline(
                number=2,
                title="What It Costs",
                what_happens=f"Following the clue forces {name} to risk the relationship or truth they value most.",
                emotional_turn="Hope becomes a difficult, personal sacrifice.",
                ending_promise="The apparent answer reveals a more dangerous question.",
            ),
            EpisodeOutline(
                number=3,
                title="The Choice",
                what_happens=f"{name} confronts the source of the conflict and chooses what to protect.",
                emotional_turn="The fear is faced rather than avoided.",
                ending_promise="The central emotional promise receives an earned payoff.",
            ),
        ],
    )


async def generate_series_plan(
    dna: CreativeDNA,
    primary: VisionCard | None,
    emit_token,
    output_language: str = "auto",
) -> SeriesPlan:
    """Plan all three linked episodes in one low-cost writing pass."""
    await emit_token("[Writer] Planning the complete three-episode story...\n")
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SERIES_SYSTEM},
            {"role": "user", "content": (
                f"Creative DNA:\n{dna.model_dump_json(indent=2)}\n\n"
                f"Chosen treatment: {primary.title if primary else 'emotional_intimacy'}\n"
                f"Treatment premise: {primary.premise if primary else dna.premise}\n\n"
                f"{_series_language_instruction(output_language)}"
            )},
        ],
        temperature=0.65,
        max_tokens=1600,
        stream=True,
    )
    full = ""
    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            full += delta

    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', full.strip(), flags=re.MULTILINE).strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return _fallback_series_plan(dna, primary)
    try:
        plan = SeriesPlan.model_validate(json.loads(match.group()))
        if [outline.number for outline in plan.episode_outlines] != [1, 2, 3]:
            raise ValueError("series outline must contain episodes 1, 2, and 3 in order")
        return plan
    except (ValueError, json.JSONDecodeError):
        return _fallback_series_plan(dna, primary)


def _dynamic_vision_fallback(dna: CreativeDNA) -> list[VisionCard]:
    """Dynamic fallback using actual DNA — not hardcoded Maya story."""
    name = dna.protagonist.name
    conflict = dna.central_conflict[:120]
    premise = dna.premise or dna.central_conflict
    companions = [c.name for c in dna.characters if c.name.lower() != name.lower()]
    team = ", ".join(companions) if companions else "the people closest to them"
    return [
        VisionCard(
            id="fractured_time",
            title="Fractured Time",
            grammar="Nonlinear — audience discovers truth before protagonist",
            premise=f"{name} hears the aftermath first, then reconstructs how {premise.lower()} pulled {team} into the truth.",
            opening_preview=f"[AMBIENCE: tense silence]\n{name.upper()}: This is not how it was supposed to end.\n[SFX: phone rings]\n[SILENCE: 1.0s]\n{name.upper()}: I know who you are.",
            emotional_trajectory="Disorientation → dread → terrible clarity",
            cliffhanger_type="Temporal — the call was made before the event happened",
            constitution_score=88,
            why_it_fits_dna=f"Mirrors the fractured reality of: {conflict}",
        ),
        VisionCard(
            id="emotional_intimacy",
            title="Emotional Intimacy",
            grammar="Relationship-first — silence and restraint carry more than action",
            premise=f"{name} and {team} sit with the emotional cost of this truth: {premise}.",
            opening_preview=f"[AMBIENCE: quiet room, distant traffic]\n[SILENCE: 2.0s]\n{name.upper()} [quietly]: I found out today.\n[SILENCE: 1.2s]\n{name.upper()}: I can't tell anyone.",
            emotional_trajectory="Quiet grief → impossible choice → devastating tenderness",
            cliffhanger_type="Emotional — someone already knows",
            constitution_score=85,
            why_it_fits_dna=f"Gives space for the core emotion to breathe: {dna.core_emotion}",
        ),
        VisionCard(
            id="kinetic_mystery",
            title="Kinetic Mystery",
            grammar="Immediate danger — reversal every 90 seconds",
            premise=f"{name} must act before {premise.lower()} turns into an irreversible loss for {team}.",
            opening_preview=f"[SFX: running footsteps]\n{name.upper()} [breathless]: The door won't open.\n[SFX: phone rings — unknown number]\n{name.upper()}: Hello?\n[SILENCE: 0.5s]\nVOICE [distorted]: Stop looking.",
            emotional_trajectory="Panic → grim focus → shocking reversal → breathless cliffhanger",
            cliffhanger_type="Physical — the threat was already inside",
            constitution_score=90,
            why_it_fits_dna=f"Externalises the internal terror of: {conflict}",
        ),
    ]


async def generate_visions(dna: CreativeDNA, emit_token) -> list[VisionCard]:
    log.info("Writer: generating visions for DNA: %s", dna.core_emotion)
    await emit_token(f"\n[WRITER] Developing 3 directorial visions for: {dna.protagonist.name}...\n\n")

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": VISION_SYSTEM},
            {"role": "user", "content": (
                f"Creative DNA:\n{dna.model_dump_json(indent=2)}\n\n"
                "Generate 3 VisionCard objects as a JSON array. "
                "Make them SPECIFIC to this story — use the protagonist's name and their conflict. "
                "Return ONLY the JSON array."
            )},
        ],
        temperature=0.85,
        max_tokens=2200,
        stream=True,
    )

    full = ""
    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            full += delta
            await emit_token(delta)

    # Robust JSON extraction
    raw = full.strip()
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
    raw = raw.strip()

    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        data = json.loads(match.group())
        visions = [VisionCard(**v) for v in data]
        # A generic or stale-model vision breaks the creator's trust.  Only
        # accept a treatment when it demonstrably carries the chosen hero.
        hero = dna.protagonist.name.lower()
        if len(visions) != 3 or any(hero not in f"{v.premise} {v.opening_preview}".lower() for v in visions):
            log.warning("Writer: generated visions lost the protagonist — using grounded treatment set")
            return _dynamic_vision_fallback(dna)
        log.info("Writer: %d visions generated", len(visions))
        return visions

    log.warning("Writer: JSON parse failed — dynamic fallback")
    return _dynamic_vision_fallback(dna)


async def generate_script(
    dna: CreativeDNA,
    selection: VisionSelection,
    visions: list[VisionCard],
    emit_token,
    output_language: str = "auto",
    episode_number: int = 1,
    episode_outline: EpisodeOutline | None = None,
    previous_continuity: str | None = None,
    feedback: EpisodeFeedback | None = None,
) -> ProductionScript:
    log.info("Writer: generating production script")
    await emit_token("\n[WRITER] Composing audio production script...\n\n")

    vision_map = {v.id: v for v in visions}
    primary = vision_map.get(selection.primary_vision_id)
    ending_instruction = (
        "End this episode on a consequential unresolved turn that pulls listeners into the next episode.\n"
        if episode_number < 3 else
        "Deliver an earned emotional payoff to the central promise. Do not end by opening a brand-new cliffhanger.\n"
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SCRIPT_SYSTEM},
            {"role": "user", "content": (
                f"Creative DNA:\n{dna.model_dump_json(indent=2)}\n\n"
                f"Primary vision: {primary.title if primary else 'emotional_intimacy'}\n"
                f"Opening from: {selection.opening_from}\n"
                f"Custom note: {selection.custom_note or 'none'}\n\n"
                f"This is Episode {episode_number} of exactly 3.\n"
                f"Episode plan: {(episode_outline.model_dump_json() if episode_outline else 'Use the chosen treatment.') }\n"
                f"Previous approved continuity: {previous_continuity or 'This is the first episode.'}\n"
                f"Creator feedback: {(feedback.model_dump_json() if feedback else 'None yet.')}\n"
                f"{ending_instruction}"
                f"{_dialogue_language_instruction(output_language)} "
                "Write a ProductionScript JSON with 18-24 lines, at least 14 dialogue lines, and enough spoken material for 80-100 seconds. "
                "Do not claim 90 seconds unless the dialogue is genuinely long enough. Audio-native. "
                "Use protagonist name and their specific situation. Return ONLY JSON."
            )},
        ],
        temperature=0.8,
        max_tokens=2500,
        stream=True,
    )

    full = ""
    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            full += delta
            await emit_token(delta)

    raw = full.strip()
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
    raw = raw.strip()

    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        data = json.loads(match.group())
        # Some otherwise-valid model responses wrap the requested payload.
        # Accept that stable envelope instead of throwing away a real script.
        if isinstance(data.get("production_script"), dict):
            data = data["production_script"]
        return ProductionScript(**data)

    log.warning("Writer: script JSON parse failed — minimal fallback")
    # A full audio-native fallback: it remains specific to the creator's
    # people and premise, and is long enough to be a meaningful playable pilot.
    name = dna.protagonist.name
    companion = next((c.name for c in dna.characters if c.name.lower() != name.lower()), "Voice")
    sound_seed = next(
        (s for s in dna.symbols if any(w in s.lower() for w in ("rain", "storm", "thunder", "cry", "phone", "door", "wind", "crowd"))),
        dna.symbols[0] if dna.symbols else f"{dna.core_emotion} atmosphere",
    )
    second_sound = dna.symbols[1] if len(dna.symbols) > 1 else sound_seed
    return ProductionScript(
        title=(episode_outline.title if episode_outline else f"{name}'s Story — Pilot"),
        estimated_duration_seconds=90,
        lines=[
            ProductionLine(type="ambience", description=f"{sound_seed}; a tense {dna.genre[0] if dna.genre else 'drama'} atmosphere", duration_seconds=6.0),
            ProductionLine(type="dialogue", character=name.upper(), text=f"I keep coming back to one thing: {dna.central_conflict[:130]}", emotion=dna.core_emotion, voice_note="intimate, vulnerable"),
            ProductionLine(type="sfx", description=f"{second_sound} grows louder around {name}", duration_seconds=2.0),
            ProductionLine(type="dialogue", character=companion.upper(), text=f"{name}, if that is true, what are we supposed to do now?", emotion="afraid"),
            ProductionLine(type="dialogue", character=name.upper(), text=f"We follow the only thing we know: {dna.non_negotiables[0][:120] if dna.non_negotiables else dna.central_conflict[:120]}", emotion="resolute"),
            ProductionLine(type="silence", duration_seconds=1.2),
            ProductionLine(type="dialogue", character=companion.upper(), text="You do not have to prove you are a hero alone.", emotion="steadying"),
            ProductionLine(type="dialogue", character=name.upper(), text=dna.central_conflict[:140], emotion="honest, voice close to breaking", voice_note="quiet, emotional"),
            ProductionLine(type="sfx", description=f"{second_sound} interrupts the room with a sharp, story-changing beat", duration_seconds=1.5),
            ProductionLine(type="dialogue", character="UNKNOWN VOICE", text=dna.non_negotiables[0][:120] if dna.non_negotiables else "You were never meant to find this.", emotion="distorted and threatening"),
            ProductionLine(type="dialogue", character=name.upper(), text="Then you should not have left a way in.", emotion="defiant"),
            ProductionLine(type="music", description="rising unresolved score", duration_seconds=4.0),
        ],
    )
