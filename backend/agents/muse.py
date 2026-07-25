"""
Muse Agent — extracts Creative DNA from any messy human input.
Uses max_retries=0 so the circuit breaker (not the SDK) controls retries.
"""
from __future__ import annotations
import os, re
from openai import AsyncOpenAI
from schemas import CreativeDNA, Protagonist, StoryCharacter
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
- Extract every meaningful character or group mentioned by the user. Invent only the minimum supporting cast required by the premise.
- Detect genre, tone words, story devices, and any film/director references. Treat references as high-level narrative grammar (for example, "slow-burn mystery"), never imitate a living director or copy a film.
- Write a one-sentence premise that uses the user's concrete situation and characters.
- non_negotiables: only facts the user explicitly stated or strongly implied.
- creative_freedom: 0=complete brief given, 100=almost nothing specified.
- Be specific. Vague DNA produces vague stories.

Return ONLY valid JSON matching the CreativeDNA schema. No markdown, no explanation.

Return every field in exactly this shape:
{"core_emotion":"string","audience_promise":"string","protagonist":{"name":"string","desire":"string","fear":"string"},"central_conflict":"string","symbols":["string"],"non_negotiables":["string"],"tone":["string"],"genre":["string"],"story_references":["string"],"characters":[{"name":"string","role":"string","relationship_to_protagonist":"string","want":"string","secret_or_tension":"string"}],"premise":"string","creative_freedom":50,"locked_fields":[]}
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
    common_words = {"The", "And", "But", "Make", "Tell", "This", "That", "When", "With", "Two", "One", "A", "An", "Like"}
    char_names = [n for n in names if n not in common_words]
    protagonist_name = char_names[0] if char_names else ("Asha" if "two strangers" in t else "Arjun")

    # Detect tone and genre from the actual words, never from the golden demo.
    tone = []
    if any(w in t for w in ["mystery", "mysterious", "strange", "weird", "unknown"]): tone.append("mysterious")
    if any(w in t for w in ["emotional", "sad", "cry", "tears", "heartbreak"]): tone.append("emotional")
    if any(w in t for w in ["thriller", "suspense", "danger", "chase"]): tone.append("tense")
    if not tone: tone = ["intimate", "character-driven"]
    genre_map = {
        "mystery": "mystery", "thriller": "thriller", "horror": "horror", "romance": "romance",
        "comedy": "comedy", "sci-fi": "science fiction", "science fiction": "science fiction",
        "fantasy": "fantasy", "crime": "crime drama", "family": "family drama", "dream": "surreal drama",
    }
    genres = [label for word, label in genre_map.items() if word in t] or ["character drama"]
    references = []
    for marker in ("like ", "in the style of ", "inspired by "):
        if marker in t:
            candidate = transcript[t.index(marker) + len(marker):].split(".")[0].strip()
            if candidate: references.append(candidate[:80])

    # Build non-negotiables from explicit statements
    non_neg = []
    sentences = transcript.split('.')
    for s in sentences:
        s = s.strip()
        if len(s) > 10 and any(w in s.lower() for w in ["but", "except", "only", "always", "never"]):
            non_neg.append(s[:80])
    if not non_neg:
        non_neg = [transcript[:80]]

    characters = [StoryCharacter(name=protagonist_name, role="protagonist", relationship_to_protagonist="self", want="make sense of what changed", secret_or_tension="the truth may cost them what they want")]
    if "two strangers" in t or "two people" in t:
        second_name = "Meera" if protagonist_name != "Meera" else "Kabir"
        characters.append(StoryCharacter(name=second_name, role="co-protagonist", relationship_to_protagonist="stranger connected by the same event", want="learn why their lives overlap", secret_or_tension="they may know more than they admit"))
    elif "sister" in t or "brother" in t:
        relation = "sister" if "sister" in t else "brother"
        characters.append(StoryCharacter(name=relation.title(), role="missing connection", relationship_to_protagonist=relation, want="be found or heard", secret_or_tension="their absence is the story's first clue"))

    return CreativeDNA(
        core_emotion=emotion,
        audience_promise=f"discover the truth behind: {transcript[:60]}...",
        protagonist=Protagonist(
            name=protagonist_name,
            desire="uncover what is really happening",
            fear="that the truth will break everything",
        ),
        central_conflict=f"Something impossible is happening: {transcript[:70]}",
        symbols=[w for w in ["a shared dream" if "dream" in t else "", "a missing message" if "message" in t or "call" in t else "", "an unanswered question"] if w],
        non_negotiables=non_neg[:3],
        tone=tone,
        genre=genres[:3],
        story_references=references,
        premise=f"{protagonist_name} must uncover what changed after {transcript[:100]}",
        characters=characters,
        creative_freedom=65,
        locked_fields=[],
    )


async def extract_dna(transcript: str, emit_token) -> CreativeDNA:
    log.info("Muse: extracting DNA (%d chars)", len(transcript))
    await emit_token(f'Analysing: "{transcript[:80]}..."\n\n')

    # Stream a compact extraction response. The SDK's supported streaming surface
    # is `create(..., stream=True)`, not the synchronous helper API.
    response = await client.chat.completions.create(
        model="gpt-4o-mini",   # faster, cheaper, handles Indian English well
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f'Input: "{transcript}"\n\nThink briefly about the core emotion, then output the JSON.'},
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
        data = json.loads(match.group())
        return CreativeDNA(**data)

    # If parsing fails, use dynamic fallback
    log.warning("Muse: JSON parse failed, using dynamic fallback")
    return _fallback_dna_from_transcript(transcript)
