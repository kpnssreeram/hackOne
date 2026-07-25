"""
Writer Agent — generates 3 Directorial Visions and the Production Script.
max_retries=0, gpt-4o-mini for speed, robust JSON extraction.
"""
from __future__ import annotations
import os, re, json
from openai import AsyncOpenAI
from schemas import CreativeDNA, VisionCard, VisionSelection, ProductionScript, ProductionLine
import logging

log = logging.getLogger("nolan.writer")

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=0, timeout=38.0)

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

SCRIPT_SYSTEM = """You are writing a production script for a 60-90 second audio drama pilot.

CRITICAL RULES:
1. Every action must be HEARABLE — use [SFX:], [AMBIENCE:], [SILENCE: Xs] tags
2. No visual-only descriptions
3. Use the protagonist's actual name and their specific situation
4. End on a strong unresolved cliffhanger
5. Keep dialogue sharp — 1-2 sentences per line max

Return ONLY valid JSON matching ProductionScript schema. No markdown.
"""


def _dynamic_vision_fallback(dna: CreativeDNA) -> list[VisionCard]:
    """Dynamic fallback using actual DNA — not hardcoded Maya story."""
    name = dna.protagonist.name
    conflict = dna.central_conflict[:60]
    return [
        VisionCard(
            id="fractured_time",
            title="Fractured Time",
            grammar="Nonlinear — audience discovers truth before protagonist",
            premise=f"{name} is already at the end. We watch them piece together how they got here.",
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
            premise=f"{name} sits with the weight of what they know, unable to tell anyone.",
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
            premise=f"{name} has 24 hours to find the truth before it finds them.",
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
        log.info("Writer: %d visions generated", len(visions))
        return visions

    log.warning("Writer: JSON parse failed — dynamic fallback")
    return _dynamic_vision_fallback(dna)


async def generate_script(
    dna: CreativeDNA,
    selection: VisionSelection,
    visions: list[VisionCard],
    emit_token,
) -> ProductionScript:
    log.info("Writer: generating production script")
    await emit_token("\n[WRITER] Composing audio production script...\n\n")

    vision_map = {v.id: v for v in visions}
    primary = vision_map.get(selection.primary_vision_id)

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SCRIPT_SYSTEM},
            {"role": "user", "content": (
                f"Creative DNA:\n{dna.model_dump_json(indent=2)}\n\n"
                f"Primary vision: {primary.title if primary else 'emotional_intimacy'}\n"
                f"Opening from: {selection.opening_from}\n"
                f"Custom note: {selection.custom_note or 'none'}\n\n"
                "Write a ProductionScript as JSON with EXACTLY these keys:\n"
                '{\n'
                '  "title": "episode title",\n'
                '  "estimated_duration_seconds": 75,\n'
                '  "lines": [\n'
                '    {"type": "ambience", "description": "...", "duration_seconds": 2.0},\n'
                '    {"type": "silence", "duration_seconds": 1.0},\n'
                '    {"type": "dialogue", "character": "NAME", "text": "...", "emotion": "..."},\n'
                '    {"type": "sfx", "description": "...", "duration_seconds": 0.5}\n'
                '  ]\n'
                '}\n'
                "60-90 seconds, audio-native, use the protagonist's real name and situation. "
                "Return ONLY the JSON."
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
        try:
            data = json.loads(match.group())
            # Fill required fields the model sometimes omits
            data.setdefault("title", f"{dna.protagonist.name}'s Story — Pilot")
            dur = (data.get("estimated_duration_seconds")
                   or data.get("duration_seconds") or data.get("duration") or 75)
            data["estimated_duration_seconds"] = int(dur)
            if data.get("lines"):
                return ProductionScript(**data)
        except Exception as exc:
            log.warning("Writer: script parse/validation failed (%s) — fallback", exc)

    log.warning("Writer: script JSON parse failed — minimal fallback")
    # Minimal dynamic fallback script
    name = dna.protagonist.name
    return ProductionScript(
        title=f"{name}'s Story — Pilot",
        estimated_duration_seconds=75,
        lines=[
            ProductionLine(type="ambience", description="quiet city night, distant sounds", duration_seconds=2.0),
            ProductionLine(type="silence", duration_seconds=1.5),
            ProductionLine(type="dialogue", character=name.upper(), text=f"This is not what I expected.", emotion="uncertain"),
            ProductionLine(type="silence", duration_seconds=0.8),
            ProductionLine(type="dialogue", character=name.upper(), text=dna.central_conflict[:100], emotion="conflicted"),
            ProductionLine(type="sfx", description="phone notification sound", duration_seconds=0.5),
            ProductionLine(type="dialogue", character=name.upper(), text="Who are you?", emotion="alarmed"),
            ProductionLine(type="silence", duration_seconds=1.0),
            ProductionLine(type="dialogue", character="VOICE", text=dna.non_negotiables[0][:80] if dna.non_negotiables else "I know the truth.", emotion="calm, deliberate"),
            ProductionLine(type="music", description="low strings, unresolved chord", duration_seconds=3.0),
        ],
    )
