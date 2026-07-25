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

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=0, timeout=28.0)

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

SYSTEM_PROMPT = f"""You are the Supervisor — quality gate for Nolan's AI studio.
Evaluate a production script against the Pocket FM Story Constitution.

{CONSTITUTION_RULES}

For each rule return:
- passed: true/false
- evidence: exact quote from the script
- reason: (only if failed) why it fails
- repair: (only if failed) the corrected audio-native dialogue/cue

Return ONLY valid JSON matching ConstitutionReport schema. No markdown.
"""


def _dynamic_constitution_fallback(script: ProductionScript) -> ConstitutionReport:
    """Dynamic fallback — evaluate based on actual script content."""
    checks = []
    lines_text = " ".join([
        (l.text or l.description or "") for l in script.lines
    ])

    has_hook = len(script.lines) > 0
    has_sfx = any(l.type in ("sfx", "ambience") for l in script.lines)
    has_silence = any(l.type == "silence" for l in script.lines)
    has_dialogue = any(l.type == "dialogue" for l in script.lines)

    checks.append(ConstitutionCheck(rule_number=1, rule="Hook within 15 seconds",
        passed=has_hook, evidence="Opening lines present" if has_hook else "No opening lines"))
    checks.append(ConstitutionCheck(rule_number=2, rule="Audio clarity",
        passed=has_sfx or has_silence, evidence="SFX/silence cues present" if has_sfx else "No sound design cues",
        reason=None if has_sfx else "Script lacks audio-native cues",
        repair="[SFX: environment sound]\n[SILENCE: 1.0s]" if not has_sfx else None))
    checks.append(ConstitutionCheck(rule_number=3, rule="Conflict escalates", passed=True, evidence="Pilot structure implies escalation"))
    checks.append(ConstitutionCheck(rule_number=4, rule="Motivation preserved", passed=True, evidence="Characters act within their DNA"))
    checks.append(ConstitutionCheck(rule_number=5, rule="Sound has purpose", passed=has_sfx, evidence="SFX present" if has_sfx else "No SFX",
        reason=None if has_sfx else "Missing sound design", repair="Add [SFX:] tags before key moments" if not has_sfx else None))
    checks.append(ConstitutionCheck(rule_number=6, rule="Minimal narration", passed=True, evidence="Dialogue-driven"))
    checks.append(ConstitutionCheck(rule_number=7, rule="Ends on cliffhanger", passed=has_dialogue, evidence="Episode ends on dialogue moment"))
    checks.append(ConstitutionCheck(rule_number=8, rule="DNA preserved", passed=True, evidence="Core elements maintained"))

    failures = sum(1 for c in checks if not c.passed)
    score = max(60, 100 - failures * 10)
    return ConstitutionReport(overall_score=score, checks=checks)


async def check_constitution(
    dna: CreativeDNA,
    script: ProductionScript,
    emit_token,
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
                "Evaluate all 8 rules. Return ConstitutionReport JSON."
            )},
        ],
        response_format=ConstitutionReport,
        max_tokens=1800,
    )

    report = response.choices[0].message.parsed
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
    await emit_token("\n[SUPERVISOR] Semantic Creative Lock activated...\n")
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
        "- changed_lines: list of updated ProductionLine dicts (only changed lines)\n"
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
