"""
Muse Agent — extracts Creative DNA from messy human input.
Handles dreams, memories, fragments, incomplete ideas.
Indian English accent hint applied to transcription upstream.
"""
from __future__ import annotations
import os
from openai import AsyncOpenAI
from schemas import CreativeDNA, Protagonist
import logging

log = logging.getLogger("nolan.muse")
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """You are the Muse — the first agent in Nolan, an AI audio storytelling studio.

Your job: take messy, incomplete human input (a dream, memory, half-formed idea, voice ramble) 
and extract its Creative DNA — the emotional fingerprint that must be protected through every 
later stage of production.

Rules:
- Never invent details the user did not imply.
- non_negotiables must be things explicitly stated or strongly implied by the user.
- tone must reflect the user's actual emotional register, not generic storytelling defaults.
- creative_freedom: 0 = creator gave a complete brief, 100 = almost nothing specified.
- Protagonist name: invent a culturally resonant name if none given (prefer South Asian names for India-first context).
- Be precise. Vague DNA produces vague stories.
"""

async def extract_dna(transcript: str, emit_token) -> CreativeDNA:
    """
    Stream-extracts Creative DNA from transcript.
    Calls emit_token(str) for each reasoning token so the UI shows live thinking.
    Returns a structured CreativeDNA object.
    """
    log.info("Muse: extracting DNA from transcript (%d chars)", len(transcript))

    # Step 1: stream reasoning to UI
    reasoning_prompt = f"""
The creator said: "{transcript}"

Think through what they really mean — what emotion drives this idea? 
What would make an audience lean forward? What must never be changed?
Reason briefly (2-3 sentences), then extract the DNA.
"""
    # Stream reasoning tokens
    async with client.chat.completions.stream(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": reasoning_prompt},
        ],
        max_tokens=300,
    ) as stream:
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                await emit_token(delta)

    # Step 2: structured extraction
    response = await client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f'Extract the Creative DNA from: "{transcript}"\n\nReturn only the structured JSON.'
            },
        ],
        response_format=CreativeDNA,
        max_tokens=600,
    )
    dna = response.choices[0].message.parsed
    log.info("Muse: DNA extracted — core_emotion=%s", dna.core_emotion)
    return dna
