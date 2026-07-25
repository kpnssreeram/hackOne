"""Visual Director — translates Nolan's approved audio story into a 9:16 edit plan."""
from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

from schemas import CreativeDNA, ProductionScript, VisualEpisodePlan

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", "replay-placeholder"))

SYSTEM = """You are Nolan's Visual Director. Turn an approved audio drama into a
90-second vertical visual episode. The generated scenes must feature an ORIGINAL,
fictional protagonist described from the Creative DNA; never name or depict a real
person. Use exactly six beats whose durations total 90 seconds: a user_video beat
(8 sec), a portrait_card beat (10 sec), and four generated_scene beats (18 sec each).
The portrait card is an unmodified creator-uploaded still and is never sent to a video
model. Make visual prompts specific: shot type, fictional subject, action, setting,
lighting, and motion. Return only JSON matching VisualEpisodePlan."""


def fallback_plan(dna: CreativeDNA, script: ProductionScript) -> VisualEpisodePlan:
    name = dna.protagonist.name
    style = f"Vertical cinematic {', '.join(dna.tone[:2])} drama; rich shadows and purposeful motion"
    return VisualEpisodePlan(
        title=script.title,
        style=style,
        protagonist_description=(f"An original fictional character named {name}; "
                                 f"their look is suggested by the story, not a real person."),
        beats=[
            {"id": "live-opening", "start_seconds": 0, "duration_seconds": 8, "kind": "user_video",
             "purpose": "Creator's live opening", "visual_prompt": "Use uploaded auditorium footage unchanged.",
             "narration_anchor": "Opening hook", "source_asset": "live_video"},
            {"id": "portrait-intro", "start_seconds": 8, "duration_seconds": 10, "kind": "portrait_card",
             "purpose": "Creator ownership card", "visual_prompt": "Slow editorial zoom over uploaded portrait; no generation.",
             "narration_anchor": "Introduce the dream", "source_asset": "portrait"},
            {"id": "dream-world", "start_seconds": 18, "duration_seconds": 18, "kind": "generated_scene",
             "purpose": "Establish the world", "visual_prompt": f"Wide vertical shot: fictional {name} alone in a rain-soaked empty railway platform at blue hour, slow dolly in, emotional mystery.",
             "narration_anchor": "Central conflict"},
            {"id": "symbol", "start_seconds": 36, "duration_seconds": 18, "kind": "generated_scene",
             "purpose": "Make the symbol tangible", "visual_prompt": "Close-up of an old phone vibrating on a metal bench, rain droplets, reflected station lights, camera slowly circles.",
             "narration_anchor": "First revelation"},
            {"id": "danger", "start_seconds": 54, "duration_seconds": 18, "kind": "generated_scene",
             "purpose": "Escalate danger", "visual_prompt": "Over-the-shoulder vertical shot of a fictional lone figure walking through an empty station tunnel; lights flicker behind them; tense slow tracking shot.",
             "narration_anchor": "Escalation"},
            {"id": "cliffhanger", "start_seconds": 72, "duration_seconds": 18, "kind": "generated_scene",
             "purpose": "Land the cliffhanger", "visual_prompt": "Extreme close-up of a cracked phone screen showing an incoming call, rain and distant train lights; camera pushes in, ending on black.",
             "narration_anchor": "Final unresolved decision"},
        ],
    )


async def plan_visual_episode(dna: CreativeDNA, script: ProductionScript) -> VisualEpisodePlan:
    if not os.getenv("OPENAI_API_KEY"):
        return fallback_plan(dna, script)
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            temperature=0.7,
            max_tokens=1600,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Creative DNA:\n{dna.model_dump_json()}\n\nProduction script:\n{script.model_dump_json()}"},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].removeprefix("json").strip()
        return VisualEpisodePlan.model_validate(json.loads(raw))
    except Exception:
        return fallback_plan(dna, script)
