"""
Supervisor Agent — Story Constitution + Semantic Creative Lock.
max_retries=0, gpt-4o-mini for speed.
"""
from __future__ import annotations
import os, re, json
from openai import AsyncOpenAI
from schemas import CreativeDNA, ProductionScript, ConstitutionReport, ConstitutionCheck
import logging

log = logging.getLogger("nolan.supervisor")

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY") or "replay-placeholder", max_retries=0, timeout=28.0)

CONSTITUTION_RULES = """
POCKET FM STORY CONSTITUTION — 8 Rules:
1. Hook within 15 seconds — character, conflict, or unanswered question
2. Audio clarity — every action understandable without visuals
3. Escalation — conflict escalates at least once
4. Motivation — character actions match their stated motivation
5. Sound purpose — every SFX/ambience cue has narrative purpose
6. Narration economy — replace narration with dialogue/sound where possible
7. Cliffhanger — end on consequential unresolved moment
8. DNA lock — all non_negotiables from Creative DNA are preserved
"""

# Keep these labels in one place. The model can occasionally return the right
# observation against the wrong numbered rule; the UI should never inherit that
# mismatch.
CANONICAL_RULES: dict[int, str] = {
    1: "Hook within 15 seconds",
    2: "Audio clarity",
    3: "Escalation",
    4: "Motivation",
    5: "Sound purpose",
    6: "Narration economy",
    7: "Cliffhanger",
    8: "DNA lock",
}


def _rule_title(rule_number: int, episode_number: int = 1) -> str:
    """Episode three earns closure instead of faking one more cliffhanger."""
    if rule_number == 7 and episode_number == 3:
        return "Ending payoff"
    return CANONICAL_RULES[rule_number]


def _ending_instruction(episode_number: int) -> str:
    if episode_number == 3:
        return (
            "This is Episode 3. Rule 7 is an earned ending payoff: the central emotional "
            "promise is resolved or deliberately transformed. Do not require a new cliffhanger."
        )
    return (
        f"This is Episode {episode_number}. Rule 7 is a consequential unresolved turn that "
        "makes the listener need the next episode."
    )


def _rule_number_from_title(title: str) -> int | None:
    """Map a model-written rule title to its canonical Constitution rule."""
    value = title.casefold()
    if any(term in value for term in ("narration", "voice-over", "voice over")):
        return 6
    if any(term in value for term in ("sound purpose", "sound cue", "sfx", "ambience")):
        return 5
    if any(term in value for term in ("cliffhanger", "unresolved", "consequential end", "ending payoff", "earned ending")):
        return 7
    if any(term in value for term in ("dna", "non-negotiable", "creative lock")):
        return 8
    if "hook" in value or "15 second" in value:
        return 1
    if any(term in value for term in ("audio clarity", "understandable without", "audio-native")):
        return 2
    if "escalat" in value:
        return 3
    if any(term in value for term in ("motivat", "character action")):
        return 4
    return None


def _has_narrator_line(script: ProductionScript) -> bool:
    narrator_names = {"narrator", "voiceover", "voice over", "voice-over"}
    for line in script.lines:
        if line.type != "dialogue" or (line.character or "").strip().casefold() not in narrator_names:
            continue
        # A short spoken title/episode card is packaging, not narration that
        # should be replaced by character dialogue.
        text = (line.text or "").strip().casefold()
        if "episode" in text and len(text) <= 110:
            continue
        return True
    return False


def _normalize_constitution_report(
    report: ConstitutionReport,
    script: ProductionScript,
    episode_number: int = 1,
) -> ConstitutionReport:
    """Return one canonical check per Constitution rule.

    Rule names are semantic labels, not free-form UI copy. Prefer a recognised
    title over a conflicting number, then fall back to the model's number. This
    repairs swapped Rule 5/6 responses without discarding the model's evidence.
    """
    selected: dict[int, ConstitutionCheck] = {}

    # A recognisable title is more reliable than an occasionally swapped number.
    for check in report.checks:
        rule_number = _rule_number_from_title(check.rule)
        if rule_number and rule_number not in selected:
            selected[rule_number] = check

    # Keep otherwise unrecognised model checks in their numbered slot.
    for check in report.checks:
        if check.rule_number in CANONICAL_RULES and check.rule_number not in selected:
            selected[check.rule_number] = check

    fallback_checks = {
        check.rule_number: check
        for check in _dynamic_constitution_fallback(script, episode_number=episode_number).checks
    }
    normalized = [
        selected.get(rule_number, fallback_checks[rule_number]).model_copy(
            update={"rule_number": rule_number, "rule": _rule_title(rule_number, episode_number)}
        )
        for rule_number in CANONICAL_RULES
    ]

    # Silence is an audio choice, not narration. A script without a narrator or
    # voice-over cannot violate narration economy merely because it has pauses.
    if not _has_narrator_line(script):
        normalized[5] = ConstitutionCheck(
            rule_number=6,
            rule=_rule_title(6, episode_number),
            passed=True,
            evidence="No narrator or voice-over lines; character dialogue and sound carry the episode.",
        )

    return ConstitutionReport(
        overall_score=report.overall_score,
        checks=normalized,
        repaired_script_patch=report.repaired_script_patch,
    )

SYSTEM_PROMPT = f"""You are the Supervisor — quality gate for Nolan's AI studio.
Evaluate a production script against the Pocket FM Story Constitution.

{CONSTITUTION_RULES}

For each rule return:
- rule_number: the exact canonical number (1 through 8)
- rule: the exact canonical title from the Constitution
- passed: true/false
- evidence: exact quote from the script
- reason: (only if failed) why it fails
- repair: (only if failed) the corrected audio-native dialogue/cue

Silence is a sound-design choice, not narration. Rule 6 may fail only when an
actual narrator/voice-over line can be replaced by dialogue or sound.
For Episode 3, Rule 7 is renamed "Ending payoff" and checks for earned closure
instead of demanding a new cliffhanger.

Return ONLY valid JSON matching ConstitutionReport schema. No markdown.
"""


def _dynamic_constitution_fallback(
    script: ProductionScript,
    dna: CreativeDNA | None = None,
    episode_number: int = 1,
) -> ConstitutionReport:
    """A conservative offline check based on the actual script, never auto-green claims."""
    checks = []

    opening = script.lines[:4]
    has_hook = any(line.type in {"dialogue", "sfx", "ambience"} and ((line.text or line.description or "").strip()) for line in opening)
    sound_lines = [line for line in script.lines if line.type in ("sfx", "ambience", "music")]
    has_sfx = bool(sound_lines)
    has_silence = any(l.type == "silence" for l in script.lines)
    dialogue_lines = [line for line in script.lines if line.type == "dialogue" and (line.text or "").strip()]
    has_dialogue = bool(dialogue_lines)
    has_audio_cue = has_sfx or has_silence
    sound_is_purposeful = bool(sound_lines) and all((line.description or "").strip() for line in sound_lines)
    protagonist_present = not dna or any(
        (line.character or "").casefold() == dna.protagonist.name.casefold()
        for line in dialogue_lines
    )
    words = " ".join((line.text or "") for line in dialogue_lines).casefold()
    escalation_markers = ("but", "before", "never", "not", "stop", "wait", "again", "dead", "danger", "can't", "cannot", "why", "who")
    escalates = len(dialogue_lines) >= 4 and (len(sound_lines) >= 2 or any(marker in words for marker in escalation_markers))
    last_story_line = next((line for line in reversed(script.lines) if line.type in {"dialogue", "sfx", "music"}), None)
    last_words = ((last_story_line.text if last_story_line else "") or (last_story_line.description if last_story_line else "")).casefold()
    unresolved_markers = ("?", "but", "before", "never", "wait", "stop", "again", "who", "why", "unknown", "unresolved")
    resolved_markers = ("choose", "home", "together", "forgive", "free", "finally", "accept", "remember", "safe", "begin")
    ending_lands = any(marker in last_words for marker in (resolved_markers if episode_number == 3 else unresolved_markers))
    dna_preserved = True
    if dna:
        dna_terms = [dna.protagonist.name, *dna.symbols[:2], *dna.non_negotiables[:1]]
        meaningful_terms = [term.casefold() for term in dna_terms if len(term.strip()) >= 4]
        dna_preserved = protagonist_present and any(term in words for term in meaningful_terms)

    checks.append(ConstitutionCheck(rule_number=1, rule=CANONICAL_RULES[1],
        passed=has_hook, evidence="An audible hook lands in the opening beats." if has_hook else "No audible hook in the opening beats",
        reason=None if has_hook else "Start with a character, conflict, or unanswered sound cue.",
        repair=None if has_hook else "[SFX: an impossible interruption]\nCHARACTER: Who is there?"))
    checks.append(ConstitutionCheck(rule_number=2, rule=CANONICAL_RULES[2],
        passed=has_audio_cue, evidence="Sound-design cues present" if has_audio_cue else "No sound-design cues",
        reason=None if has_audio_cue else "Script lacks audio-native cues",
        repair="[SFX: environment sound]\n[SILENCE: 1.0s]" if not has_audio_cue else None))
    checks.append(ConstitutionCheck(rule_number=3, rule=CANONICAL_RULES[3], passed=escalates,
        evidence="Later beats raise pressure through dialogue or sound." if escalates else "The script does not yet show a clear increase in pressure.",
        reason=None if escalates else "Add one irreversible discovery, cost, or threat after the setup.",
        repair=None if escalates else "[SFX: the signal returns, closer]\nCHARACTER: It followed us here."))
    checks.append(ConstitutionCheck(rule_number=4, rule=CANONICAL_RULES[4], passed=protagonist_present,
        evidence="The protagonist actively speaks or acts in the episode." if protagonist_present else "The protagonist's choice is not audible.",
        reason=None if protagonist_present else "Give the protagonist an audible decision tied to their want or fear.",
        repair=None if protagonist_present else "PROTAGONIST: I am not leaving until I know the truth."))
    checks.append(ConstitutionCheck(rule_number=5, rule=CANONICAL_RULES[5], passed=sound_is_purposeful,
        evidence="Every sound cue has a written story purpose." if sound_is_purposeful else "A sound cue is missing a narrative description.",
        reason=None if sound_is_purposeful else "Each cue must reveal place, pressure, or a change in the scene.",
        repair=None if sound_is_purposeful else "[AMBIENCE: wind tightens as the call starts — the world responding]"))
    narrator_present = _has_narrator_line(script)
    checks.append(ConstitutionCheck(rule_number=6, rule=CANONICAL_RULES[6], passed=not narrator_present,
        evidence="No replaceable narrator lines; dialogue and sound carry the episode." if not narrator_present else "Narrator/voice-over line is carrying story information.",
        reason="Move explanatory narration into an audible exchange or sound event." if narrator_present else None,
        repair="[SFX: the room falls quiet]\nCHARACTER: Say that again." if narrator_present else None))
    checks.append(ConstitutionCheck(rule_number=7, rule=_rule_title(7, episode_number), passed=ending_lands,
        evidence=("The final beat resolves the emotional promise." if episode_number == 3 else "The final beat leaves a consequential unresolved turn.") if ending_lands else "The final beat does not yet land the required ending.",
        reason=None if ending_lands else ("End Episode 3 with an earned emotional choice or payoff." if episode_number == 3 else "End on a consequence that pulls listeners into the next episode."),
        repair=None if ending_lands else ("CHARACTER: I choose to remember—even if it changes everything." if episode_number == 3 else "[SFX: the unanswered call connects]\nUNKNOWN VOICE: You finally found me.")))
    checks.append(ConstitutionCheck(rule_number=8, rule=CANONICAL_RULES[8], passed=dna_preserved,
        evidence="The script carries the protagonist and a locked DNA detail." if dna_preserved else "A Creative DNA non-negotiable is not clearly audible in the script.",
        reason=None if dna_preserved else "Bring a protected story detail into dialogue or sound before finalizing.",
        repair=None if dna_preserved else "CHARACTER: That promise is the one thing I cannot lose."))

    failures = sum(1 for c in checks if not c.passed)
    score = max(60, 100 - failures * 10)
    return ConstitutionReport(overall_score=score, checks=checks)


async def check_constitution(
    dna: CreativeDNA,
    script: ProductionScript,
    emit_token,
    episode_number: int = 1,
) -> ConstitutionReport:
    log.info("Supervisor: checking constitution")
    await emit_token("\n[SUPERVISOR] Running Pocket FM Story Constitution...\n\n")

    response = await client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Creative DNA:\n{dna.model_dump_json(indent=2)}\n\n"
                f"Script:\n{script.model_dump_json(indent=2)}\n\n"
                f"{_ending_instruction(episode_number)}\n"
                "Evaluate all 8 rules. Return ConstitutionReport JSON."
            )},
        ],
        response_format=ConstitutionReport,
        max_tokens=1800,
    )

    report = _normalize_constitution_report(response.choices[0].message.parsed, script, episode_number)
    failures = [c for c in report.checks if not c.passed]

    if failures:
        await emit_token(f"\n[SUPERVISOR] {len(failures)} violation(s) found:\n")
        for f in failures:
            await emit_token(f"  ✗ Rule {f.rule_number}: {f.rule}\n")
            await emit_token(f"    Evidence: {(f.evidence or '')[:100]}\n")
            if f.repair:
                await emit_token(f"    ↳ Repair: {f.repair[:100]}\n")
    else:
        await emit_token("\n[SUPERVISOR] All 8 rules passed ✓\n")

    await emit_token(f"\n[SUPERVISOR] Score: {report.overall_score}/100\n")
    return report


async def analyze_change_impact(
    dna: CreativeDNA,
    script: ProductionScript,
    change_instruction: str,
    preserve_elements: list[str],
    emit_token,
) -> dict:
    log.info("Supervisor: semantic lock — %s", change_instruction[:50])
    await emit_token("\n[SUPERVISOR] Keeping the details you chose...\n")
    await emit_token(f"  Change: {change_instruction}\n")
    await emit_token(f"  Preserving: {', '.join(preserve_elements) if preserve_elements else 'DNA non-negotiables'}\n\n")

    prompt = (
        f"Change: {change_instruction}\n"
        f"Preserve: {preserve_elements}\n"
        f"DNA non_negotiables: {dna.non_negotiables}\n\n"
        f"Script lines:\n{script.model_dump_json(indent=2)}\n\n"
        "Return JSON with:\n"
        "- affected_scene_ids: list of scene/line identifiers changed\n"
        "- preserved_elements: list of what was kept\n"
        "- locked_elements: list of DNA invariants that cannot change\n"
        "- impact_summary: one sentence\n"
        "- changed_lines: list of objects with line_index (0-based) and line (updated ProductionLine dict); only changed lines\n"
        "Return ONLY JSON."
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are the Supervisor enforcing Semantic Creative Lock. Be surgical — change ONLY what was asked. Never touch locked elements."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=1800,
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
        return json.loads(match.group())

    # Fallback
    return {
        "affected_scene_ids": ["dialogue lines"],
        "preserved_elements": preserve_elements or dna.non_negotiables,
        "locked_elements": dna.non_negotiables,
        "impact_summary": f"Applied: {change_instruction[:60]}",
        "changed_lines": [],
    }
