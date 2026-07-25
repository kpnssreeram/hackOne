"""
Muse Agent — extracts Creative DNA from any messy human input.
Uses max_retries=0 so the circuit breaker (not the SDK) controls retries.
"""
from __future__ import annotations
import os, re
from openai import AsyncOpenAI
from schemas import CreativeDNA, Protagonist
import logging

log = logging.getLogger("nolan.muse")

# max_retries=0 — let OUR circuit breaker handle failures, not the SDK
client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=0,
    timeout=28.0,
)

SYSTEM_PROMPT = """You are the Muse — the first AI agent in Nolan, an audio storytelling studio.

Your job: extract the Creative DNA from any messy human input — a dream, memory, voice note, or rough idea.

Rules:
- Core emotion must come from what the USER actually said, not a generic default.
- Protagonist name: if not given, invent one culturally appropriate (South Asian names preferred).
- non_negotiables: only facts the user explicitly stated or strongly implied.
- creative_freedom: 0=complete brief given, 100=almost nothing specified.
- Be specific. Vague DNA produces vague stories.

Return ONLY valid JSON matching the CreativeDNA schema. No markdown, no explanation.
"""


def _fallback_dna_from_transcript(transcript: str) -> CreativeDNA:
    """
    Build a plausible CreativeDNA from the user's actual words
    without any API call. Used when circuit breaker fires.
    """
    t = transcript.lower()

    # Detect emotion keywords
    if any(w in t for w in ["forgot", "forget", "forgotten", "invisible", "ignored"]):
        emotion = "fear of being forgotten or erased"
    elif any(w in t for w in ["dead", "died", "death", "ghost", "passed"]):
        emotion = "grief tangled with mystery"
    elif any(w in t for w in ["love", "romance", "heart", "miss"]):
        emotion = "longing and unresolved connection"
    elif any(w in t for w in ["danger", "escape", "run", "chase", "threat"]):
        emotion = "survival instinct vs. inner fear"
    elif any(w in t for w in ["dream", "nightmare", "sleep"]):
        emotion = "the terror and wonder of the subconscious"
    else:
        emotion = "a deep unresolved human conflict"

    # Extract a name if present (capitalised word that isn't sentence-start)
    names = re.findall(r'\b[A-Z][a-z]{2,}\b', transcript)
    common_words = {"The", "And", "But", "Make", "Tell", "This", "That", "When", "With"}
    char_names = [n for n in names if n not in common_words]
    protagonist_name = char_names[0] if char_names else "Arjun"

    # Detect tone
    tone = []
    if any(w in t for w in ["mystery", "mysterious", "strange", "weird", "unknown"]): tone.append("mysterious")
    if any(w in t for w in ["emotional", "sad", "cry", "tears", "heartbreak"]): tone.append("emotional")
    if any(w in t for w in ["thriller", "suspense", "danger", "chase"]): tone.append("tense")
    if not tone: tone = ["mysterious", "emotional"]

    # Build non-negotiables from explicit statements
    non_neg = []
    sentences = transcript.split('.')
    for s in sentences:
        s = s.strip()
        if len(s) > 10 and any(w in s.lower() for w in ["but", "except", "only", "always", "never"]):
            non_neg.append(s[:80])
    if not non_neg:
        non_neg = [transcript[:80]]

    return CreativeDNA(
        core_emotion=emotion,
        audience_promise=f"discover the truth behind: {transcript[:60]}...",
        protagonist=Protagonist(
            name=protagonist_name,
            desire="uncover what is really happening",
            fear="that the truth will break everything",
        ),
        central_conflict=f"Something impossible is happening: {transcript[:70]}",
        symbols=["unanswered call", "empty room", "old memory"],
        non_negotiables=non_neg[:3],
        tone=tone,
        creative_freedom=65,
        locked_fields=[],
    )


async def extract_dna(transcript: str, emit_token) -> CreativeDNA:
    log.info("Muse: extracting DNA (%d chars)", len(transcript))
    await emit_token(f'Analysing: "{transcript[:80]}..."\n\n')

    # Stream reasoning first
    response = await client.chat.completions.create(
        model="gpt-4o-mini",   # faster, cheaper, handles Indian English well
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f'Input: "{transcript}"\n\n'
                "Fill EVERY field of this exact JSON structure based on the input. "
                "Use the input's real people, feelings, and events — do not invent an unrelated plot:\n"
                '{\n'
                '  "core_emotion": "the true emotional core, from the input",\n'
                '  "audience_promise": "what the listener will discover",\n'
                '  "protagonist": {"name": "a name (invent a fitting one if none given)", "desire": "what they want", "fear": "what they fear"},\n'
                '  "central_conflict": "the core tension",\n'
                '  "symbols": ["three", "evocative", "symbols"],\n'
                '  "non_negotiables": ["facts the user explicitly stated"],\n'
                '  "tone": ["two", "tone words"],\n'
                '  "creative_freedom": 65\n'
                '}\n'
                "Return ONLY the completed JSON."
            )},
        ],
        max_tokens=700,
        stream=True,
    )
    full = ""
    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            full += delta
            await emit_token(delta)

    # Parse JSON from response
    raw = full.strip()
    # Strip markdown code fences if present
    raw = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'^```\s*', '', raw, flags=re.MULTILINE)
    raw = raw.strip()

    # Find the JSON object
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        import json
        try:
            data = json.loads(match.group())
        except Exception:
            log.warning("Muse: JSON decode failed, using dynamic fallback")
            return _fallback_dna_from_transcript(transcript)

        # Merge model output over a smart fallback so partial/misshaped JSON
        # still yields a valid DNA that reflects the user's actual words.
        base = _fallback_dna_from_transcript(transcript).model_dump()
        prot = data.pop("protagonist", None)
        for k, v in data.items():
            if v:
                base[k] = v
        if isinstance(prot, dict):
            base["protagonist"].update({k: v for k, v in prot.items() if v})
        try:
            return CreativeDNA(**base)
        except Exception as exc:
            log.warning("Muse: merge validation failed (%s), using fallback", exc)
            return _fallback_dna_from_transcript(transcript)

    # If parsing fails, use dynamic fallback
    log.warning("Muse: JSON parse failed, using dynamic fallback")
    return _fallback_dna_from_transcript(transcript)
