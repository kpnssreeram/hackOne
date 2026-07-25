"""
Supervisor Agent — evaluates script against the Pocket FM Story Constitution.
Provides evidence-backed violation reports and targeted repairs.
"""
from __future__ import annotations
import os
from openai import AsyncOpenAI
from schemas import CreativeDNA, ProductionScript, ConstitutionReport, ConstitutionCheck
import logging

log = logging.getLogger("nolan.supervisor")
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

CONSTITUTION_RULES = """
POCKET FM STORY CONSTITUTION — 8 Rules

1. Hook: Establish character, conflict, or an unanswered question within 15 seconds.
2. Audio clarity: Every action must be understandable without visuals. No visual-only blocking.
3. Escalation: Conflict escalates at least once within the pilot.
4. Motivation: Character actions are consistent with their stated motivation.
5. Sound purpose: Every SFX/ambience cue has narrative or atmospheric purpose.
6. Narration: Replace unnecessary narration with dialogue, silence, or sound.
7. Cliffhanger: Episode ends on a consequential, unresolved decision/danger/revelation.
8. DNA lock: Every locked Creative DNA invariant is preserved (core_emotion, non_negotiables).
"""

SYSTEM_PROMPT = f"""You are the Supervisor in Nolan's creative studio.
You evaluate a Production Script against the Pocket FM Story Constitution.

{CONSTITUTION_RULES}

For each rule:
- passed: true/false
- evidence: exact quote or scene reference from the script proving your verdict
- reason: (only if failed) WHY it fails
- repair: (only if failed) the minimal corrected dialogue/cue that fixes the violation

Be strict. Evidence must be specific. Repairs must be audio-native.
Return a ConstitutionReport JSON. No markdown.
"""


async def check_constitution(
    dna: CreativeDNA,
    script: ProductionScript,
    emit_token,
) -> ConstitutionReport:
    log.info("Supervisor: checking constitution")
    await emit_token("\n[Supervisor] Running Pocket FM Story Constitution...\n\n")

    response = await client.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Creative DNA:\n{dna.model_dump_json(indent=2)}\n\n"
                    f"Production Script:\n{script.model_dump_json(indent=2)}\n\n"
                    "Evaluate all 8 rules. Return ConstitutionReport JSON."
                ),
            },
        ],
        response_format=ConstitutionReport,
        max_tokens=2000,
    )

    report = response.choices[0].message.parsed

    # Stream a human-readable summary of violations
    failures = [c for c in report.checks if not c.passed]
    if failures:
        await emit_token(f"\n[Supervisor] Found {len(failures)} violation(s):\n")
        for f in failures:
            await emit_token(f"\n  RULE {f.rule_number}: {f.rule}\n")
            await emit_token(f"  Evidence: {f.evidence[:120]}...\n")
            await emit_token(f"  Repair: {(f.repair or '')[:100]}...\n")
    else:
        await emit_token("\n[Supervisor] All 8 rules passed. Script approved.\n")

    log.info("Supervisor: score=%d, violations=%d", report.overall_score, len(failures))
    return report


async def analyze_change_impact(
    dna: CreativeDNA,
    script: ProductionScript,
    change_instruction: str,
    preserve_elements: list[str],
    emit_token,
) -> dict:
    """
    Semantic Creative Lock — identifies affected scenes and locked elements.
    Returns {affected_scene_ids, preserved_elements, locked_elements, changed_scenes}.
    """
    log.info("Supervisor: analyzing change impact")
    await emit_token("\n[Supervisor] Activating Semantic Creative Lock...\n\n")

    prompt = (
        f"Change instruction: {change_instruction}\n"
        f"Preserve explicitly: {preserve_elements}\n"
        f"Creative DNA locked fields: {dna.non_negotiables}\n\n"
        f"Current script:\n{script.model_dump_json(indent=2)}\n\n"
        "Identify:\n"
        "1. Which scenes/lines are affected by the change\n"
        "2. Which elements must be preserved (locked_elements)\n"
        "3. Rewrite ONLY the affected scenes with the change applied\n"
        "4. Confirm all preserved/locked elements are untouched\n\n"
        "Return JSON with keys: affected_scene_ids (list[str]), "
        "preserved_elements (list[str]), locked_elements (list[str]), "
        "impact_summary (str), changed_lines (list of ProductionLine dicts)"
    )

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are the Supervisor enforcing Semantic Creative Lock. Be surgical — change only what was asked. Never touch locked elements."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,   # low temp for precise surgical edits
        max_tokens=2000,
        stream=True,
    )

    full = ""
    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            full += delta
            await emit_token(delta)

    import json
    raw = full.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(raw)
