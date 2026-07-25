"""
Writer Agent — generates three genuinely different Directorial Visions
and the full Production Script from the selected vision.
"""
from __future__ import annotations
import os
import json
from openai import AsyncOpenAI
from schemas import CreativeDNA, VisionCard, VisionSelection, ProductionScript, ProductionLine
import logging

log = logging.getLogger("nolan.writer")
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

VISION_SYSTEM = """You are the Writer in Nolan's creative studio.
You generate three Directorial Visions — genuinely different narrative grammars, NOT paraphrases.

The three grammar types:
- fractured_time: nonlinear, audience knows more than protagonist, temporal misdirection
- emotional_intimacy: relationship-first, silence carries weight, restrained, internal
- kinetic_mystery: immediate danger, reversal every 90 seconds, urgent, external

Each vision must:
1. Fit the Creative DNA — core_emotion, non_negotiables, tone must all be present
2. Have a distinct opening that proves it follows its grammar (not just a word change)
3. End on a different type of cliffhanger
4. Score the Story Constitution honestly (0-100)

Return valid JSON matching the VisionCard schema for all three visions in an array.
"""

SCRIPT_SYSTEM = """You are the Writer generating a final Production Script for audio drama.

Rules for audio-native writing:
- Every action must be hearable (SFX, dialogue, ambience) — no visual-only descriptions
- Use [AMBIENCE:], [SFX:], [MUSIC:], [SILENCE: Xs] tags before dialogue lines
- Silence is a tool — use it deliberately (0.5s to 2.0s)
- Keep total runtime 60-90 seconds
- Dialogue must reveal character through word choice, not description
- Each character's voice must be distinct without a narrator telling us who they are
- End on the strongest unresolved moment possible

Return valid JSON matching the ProductionScript schema.
"""


async def generate_visions(dna: CreativeDNA, emit_token) -> list[VisionCard]:
    log.info("Writer: generating 3 visions")

    await emit_token("\n[Writer] Developing three directorial visions...\n\n")

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": VISION_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Creative DNA:\n{dna.model_dump_json(indent=2)}\n\n"
                    "Generate three VisionCard objects as a JSON array. "
                    "Each must follow its grammar strictly. "
                    "Return only the JSON array, no markdown."
                ),
            },
        ],
        temperature=0.85,
        max_tokens=2000,
        stream=True,
    )

    full_text = ""
    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            full_text += delta
            await emit_token(delta)

    # Parse the JSON
    raw = full_text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    visions = [VisionCard(**v) for v in data]
    log.info("Writer: generated %d visions", len(visions))
    return visions


async def generate_script(
    dna: CreativeDNA,
    selection: VisionSelection,
    visions: list[VisionCard],
    emit_token,
) -> ProductionScript:
    log.info("Writer: generating production script")
    await emit_token("\n[Writer] Composing production script...\n\n")

    # Build the selected vision brief
    vision_map = {v.id: v for v in visions}
    primary = vision_map.get(selection.primary_vision_id)

    brief = (
        f"Opening from: {vision_map[selection.opening_from].title}\n"
        f"Relationship from: {vision_map[selection.relationship_from].title}\n"
        f"Ending from: {vision_map[selection.ending_from].title}\n"
        f"Primary grammar: {primary.grammar if primary else 'emotional_intimacy'}\n"
        f"Custom note: {selection.custom_note or 'None'}\n"
    )

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SCRIPT_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Creative DNA:\n{dna.model_dump_json(indent=2)}\n\n"
                    f"Vision selection:\n{brief}\n\n"
                    "Write the full ProductionScript JSON. "
                    "60-90 seconds. Audio-native. No visual-only actions. "
                    "Return only the JSON, no markdown."
                ),
            },
        ],
        temperature=0.8,
        max_tokens=2500,
        stream=True,
    )

    full_text = ""
    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            full_text += delta
            await emit_token(delta)

    raw = full_text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    script = ProductionScript(**data)
    log.info("Writer: script generated — %d lines, ~%ds",
             len(script.lines), script.estimated_duration_seconds)
    return script
