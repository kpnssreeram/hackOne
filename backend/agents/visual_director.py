"""Visual Director — translates Nolan's approved audio story into a 9:16 edit plan."""
from __future__ import annotations

import base64
import asyncio
import html
import json
import logging
import os
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from schemas import CreativeDNA, ProductionScript, VisualAsset, VisualEpisodePlan

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY") or "replay-placeholder")
log = logging.getLogger("nolan.visual_director")

SYSTEM = """You are Nolan's Visual Director. Turn an approved audio drama into a
vertical visual episode whose exact duration is provided with the request. The generated scenes must feature an ORIGINAL,
fictional protagonist described from the Creative DNA; never name or depict a real
person.

You receive optional creator media metadata. Treat it as editorial material:
- The two supplied `video` assets must each appear as a `user_video` beat and
  remain unchanged; never invent a missing upload.
- No photo or place-reference assets are part of a video series.

Use exactly six beats whose durations total the requested audio length. Make visual
prompts specific: shot type, fictional subject, action, setting, lighting, and motion.
Return only JSON matching VisualEpisodePlan."""


def _cover_prompt(dna: CreativeDNA, script: ProductionScript, has_reference: bool = False, creator_prompt: str = "") -> str:
    """Keep image generation grounded in the approved story and optional consented reference."""
    symbols = ", ".join(dna.symbols[:3]) or "the story's central symbol"
    genre = ", ".join(dna.genre[:2]) or "cinematic drama"
    tone = ", ".join(dna.tone[:2]) or "emotionally charged"
    return f"""Create one original cinematic episode-cover image for an audio drama.
Compose it for a portrait crop: keep the fictional protagonist and central symbol
prominent in the middle of the frame. This is a fictional story poster, not a
portrait of any real person, celebrity, brand, logo, watermark, or readable text.

Story details for visual inspiration only:
Title: {script.title}
Genre: {genre}
Core emotion: {dna.core_emotion}
Protagonist: an original fictional character named {dna.protagonist.name}
Central conflict: {dna.central_conflict}
Symbols: {symbols}
Tone: {tone}
Creator's poster direction: {creator_prompt[:1600] or "Use the story's most visually arresting emotional moment."}

Use the high-contrast, practical-light suspense language of a modern Hollywood
thriller: monumental scale, tactile shadows, bold negative space, and a sense of
time folding in on itself. Do not copy any existing film or director. Leave clean
negative space for Nolan to add the title and credits. {"Use the uploaded creator image only as a consented color, composition, and mood reference; transform it into an original fictional poster rather than reproducing an identifiable person." if has_reference else ""} Return only the image."""


async def generate_episode_cover(dna: CreativeDNA, script: ProductionScript, reference_image: Path | None = None, creator_prompt: str = "") -> bytes | None:
    """Generate a cover when image access is available; callers can use the SVG fallback."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        params = {
            "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
            "prompt": _cover_prompt(dna, script, bool(reference_image), creator_prompt),
            "n": 1,
            "quality": "standard",
            "response_format": "b64_json",
            "size": "1024x1024",
        }
        if reference_image and reference_image.exists():
            with reference_image.open("rb") as source:
                response = await client.images.edit(image=source, **params)
        else:
            response = await client.images.generate(**params)
        image = response.data[0] if response.data else None
        encoded = getattr(image, "b64_json", None)
        if not encoded:
            log.warning("Image generation returned no image bytes")
            return None
        return base64.b64decode(encoded, validate=True)
    except Exception as exc:
        # A cover is an enhancement, so an unavailable image provider must not
        # block a completed audio episode.
        log.warning("Episode cover generation failed: %s", exc)
        return None


def _svg_text(value: str, limit: int) -> str:
    return html.escape(" ".join(value.split())[:limit])


def fallback_cover_svg(dna: CreativeDNA, script: ProductionScript) -> bytes:
    """Make the cover feature useful in replay/offline mode too."""
    title = _svg_text(script.title, 56) or "Nolan Episode"
    protagonist = _svg_text(dna.protagonist.name, 32) or "The protagonist"
    emotion = _svg_text(dna.core_emotion, 72)
    symbol = _svg_text(dna.symbols[0] if dna.symbols else "a hidden signal", 48)
    cast_names = [dna.protagonist.name] + [
        character.name for character in dna.characters
        if character.name != dna.protagonist.name
    ]
    cast = _svg_text(" • ".join(cast_names[:4]), 90)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1536" viewBox="0 0 1024 1536" role="img" aria-label="{title}">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#130d2b"/>
      <stop offset="54%" stop-color="#4b2b83"/>
      <stop offset="100%" stop-color="#ed6f8f"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="45%" r="48%">
      <stop offset="0%" stop-color="#f9cf91" stop-opacity=".9"/>
      <stop offset="100%" stop-color="#f9cf91" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1024" height="1536" fill="url(#sky)"/>
  <rect width="1024" height="1536" fill="url(#glow)"/>
  <circle cx="744" cy="360" r="210" fill="#fff0cf" opacity=".14"/>
  <path d="M0 1150 C190 1010 318 1220 490 1090 C650 968 823 1125 1024 974 L1024 1536 L0 1536 Z" fill="#120c25" opacity=".86"/>
  <path d="M0 1220 C245 1120 380 1290 565 1170 C710 1078 850 1170 1024 1088" fill="none" stroke="#f9cf91" stroke-width="8" opacity=".52"/>
  <rect x="96" y="166" width="94" height="8" rx="4" fill="#f9cf91"/>
  <text x="96" y="252" fill="#f9cf91" font-family="Arial, sans-serif" font-size="28" font-weight="700" letter-spacing="7">NOLAN ORIGINAL</text>
  <text x="96" y="1002" fill="#ffffff" font-family="Georgia, serif" font-size="88" font-weight="700">{title}</text>
  <text x="96" y="1080" fill="#f6d8e5" font-family="Arial, sans-serif" font-size="34">{protagonist} • {symbol}</text>
  <text x="96" y="1160" fill="#ffffff" font-family="Arial, sans-serif" font-size="25" letter-spacing="2">STARRING {cast}</text>
  <text x="96" y="1230" fill="#f9cf91" font-family="Arial, sans-serif" font-size="23" letter-spacing="3">DIRECTED BY NOLAN</text>
  <text x="96" y="1402" fill="#ffffff" font-family="Arial, sans-serif" font-size="30" opacity=".86">{emotion}</text>
  <text x="96" y="1454" fill="#f9cf91" font-family="Arial, sans-serif" font-size="23" letter-spacing="4">AUDIO DRAMA</text>
</svg>"""
    return svg.encode("utf-8")


def _first_asset(assets: list[VisualAsset], kind: str) -> VisualAsset | None:
    return next((asset for asset in assets if asset.kind == kind and asset.consented), None)


def fallback_plan(
    dna: CreativeDNA,
    script: ProductionScript,
    assets: list[VisualAsset] | None = None,
    target_duration_seconds: int | None = None,
) -> VisualEpisodePlan:
    """Make a usable, asset-aware low-credit edit plan without generating video."""
    assets = assets or []
    clips = [asset for asset in assets if asset.kind == "video" and asset.consented]
    clip = clips[0] if clips else None
    second_clip = clips[1] if len(clips) > 1 else None
    photo = _first_asset(assets, "photo")
    place = _first_asset(assets, "place_reference")
    name = dna.protagonist.name
    target_duration = max(60, int(target_duration_seconds or 90))
    style = f"Vertical cinematic {', '.join(dna.tone[:2])} drama; rich shadows and purposeful motion"
    place_direction = (
        f"Match the supplied place reference ({place.filename}) as the location palette and architecture; "
        "keep the story character original and fictional."
        if place else
        "Build the location from the story's sound and emotional world."
    )
    opening = {
        "id": "live-opening" if clip else "story-opening",
        "start_seconds": 0,
        "duration_seconds": 8,
        "kind": "user_video" if clip else "generated_scene",
        "purpose": "Creator's opening footage" if clip else "Open inside the story world",
        "visual_prompt": (
            f"Use {clip.filename} unchanged as the real opening footage; crop and transition only."
            if clip else
            f"Wide vertical opening: fictional {name} hears the first sign of danger; {place_direction}"
        ),
        "narration_anchor": "Opening hook",
        "source_asset": clip.filename if clip else (place.filename if place else None),
    }
    second_beat = {
        "id": "live-turn" if second_clip else ("photo-intro" if photo else "title-intro"),
        "start_seconds": 8,
        "duration_seconds": 10,
        "kind": "user_video" if second_clip else ("portrait_card" if photo else "title_card"),
        "purpose": "Creator's second source video" if second_clip else ("Creator photo moment" if photo else "Set the story title and emotional promise"),
        "visual_prompt": (
            f"Use {second_clip.filename} unchanged as the second source video; crop and transition only."
            if second_clip else
            f"Use {photo.filename} unchanged with a slow editorial zoom; do not generate or alter the person."
            if photo else
            f"Minimal vertical title card for {script.title}, using the story's central symbol and textured atmosphere."
        ),
        "narration_anchor": "Introduce the dream",
        "source_asset": second_clip.filename if second_clip else (photo.filename if photo else None),
    }
    beats = [
        opening,
        second_beat,
        {"id": "dream-world", "start_seconds": 18, "duration_seconds": 18, "kind": "generated_scene",
         "purpose": "Establish the world", "visual_prompt": f"Wide vertical shot: fictional {name} alone at blue hour, slow dolly in, emotional mystery. {place_direction}",
         "narration_anchor": "Central conflict", "source_asset": place.filename if place else None},
        {"id": "symbol", "start_seconds": 36, "duration_seconds": 18, "kind": "generated_scene",
         "purpose": "Make the symbol tangible", "visual_prompt": "Close-up of an old phone vibrating on a metal bench, rain droplets, reflected station lights, camera slowly circles.",
         "narration_anchor": "First revelation"},
        {"id": "danger", "start_seconds": 54, "duration_seconds": 18, "kind": "generated_scene",
         "purpose": "Escalate danger", "visual_prompt": "Over-the-shoulder vertical shot of a fictional lone figure walking through an empty station tunnel; lights flicker behind them; tense slow tracking shot.",
         "narration_anchor": "Escalation"},
        {"id": "cliffhanger", "start_seconds": 72, "duration_seconds": 18, "kind": "generated_scene",
         "purpose": "Land the cliffhanger", "visual_prompt": "Extreme close-up of a cracked phone screen showing an incoming call, rain and distant train lights; camera pushes in, ending on black.",
         "narration_anchor": "Final unresolved decision"},
    ]
    base, remainder = divmod(target_duration, len(beats))
    cursor = 0
    for index, beat in enumerate(beats):
        duration = base + (1 if index < remainder else 0)
        beat["start_seconds"] = cursor
        beat["duration_seconds"] = duration
        cursor += duration
    return VisualEpisodePlan(
        title=script.title,
        target_duration_seconds=target_duration,
        style=style,
        protagonist_description=(f"An original fictional character named {name}; "
                                 f"their look is suggested by the story, not a real person."),
        beats=beats,
    )


async def plan_visual_episode(
    dna: CreativeDNA,
    script: ProductionScript,
    assets: list[VisualAsset] | None = None,
    target_duration_seconds: int | None = None,
) -> VisualEpisodePlan:
    assets = assets or []
    if not os.getenv("OPENAI_API_KEY"):
        return fallback_plan(dna, script, assets, target_duration_seconds)
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            temperature=0.7,
            max_tokens=1600,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": (
                    f"Creative DNA:\n{dna.model_dump_json()}\n\n"
                    f"Production script:\n{script.model_dump_json()}\n\n"
                    "Creator media metadata (use only as unchanged editorial video assets):\n"
                    f"{json.dumps([asset.model_dump() for asset in assets])}\n\n"
                    f"The final audio master is {target_duration_seconds or 90} seconds. "
                    "Make the six beat start times and durations add up to that exact length."
                )},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].removeprefix("json").strip()
        plan = VisualEpisodePlan.model_validate(json.loads(raw))
        desired_duration = max(60, int(target_duration_seconds or 90))
        # A model plan that forgets a creator upload defeats the point of
        # collecting it. Use the deterministic plan instead of pretending the
        # supplied assets were respected.
        named_assets = {asset.filename for asset in assets if asset.consented}
        has_all_video_slots = all(
            any(beat.source_asset == asset.filename and beat.kind == "user_video" for beat in plan.beats)
            for asset in assets if asset.kind == "video" and asset.consented
        )
        if (
            plan.target_duration_seconds != desired_duration
            or sum(beat.duration_seconds for beat in plan.beats) != desired_duration
            or (named_assets and (not has_all_video_slots or not any(beat.source_asset in named_assets for beat in plan.beats)))
        ):
            return fallback_plan(dna, script, assets, target_duration_seconds)
        return plan
    except Exception:
        return fallback_plan(dna, script, assets, target_duration_seconds)


def _teaser_prompt(dna: CreativeDNA, plan: VisualEpisodePlan) -> str:
    """Build a short, safe text-only Sora prompt from Nolan's visual plan.

    Creator uploads deliberately stay out of this request. Sora currently rejects
    human likeness uploads, and Nolan must not turn a creator's photo into a
    generated character.
    """
    generated = next((beat for beat in plan.beats if beat.kind == "generated_scene"), None)
    direction = generated.visual_prompt if generated else plan.style
    return (
        "Create a 20-second vertical cinematic teaser for an original fictional audio drama. "
        "Do not depict any real person, celebrity, copyrighted character, logo, or readable text. "
        f"Story tone: {dna.core_emotion}. Visual style: {plan.style}. "
        f"Shot direction: {direction} "
        "Use one original fictional protagonist, purposeful camera motion, cinematic lighting, "
        "and end on an unresolved visual beat. No dialogue or music is required."
    )


async def start_video_teaser(
    dna: CreativeDNA,
    plan: VisualEpisodePlan,
    reference_image: Path | None = None,
) -> dict:
    """Start the generated scene that anchors one explicit episode-video render."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Add OPENAI_API_KEY before making a video teaser")
    form = {
        "model": os.getenv("OPENAI_VIDEO_MODEL", "sora-2"),
        "prompt": _teaser_prompt(dna, plan),
        "size": "720x1280",
        "seconds": "20",
    }
    files: list[tuple[str, tuple[object, ...]]] = [
        (key, (None, value)) for key, value in form.items()
    ]
    if reference_image and reference_image.exists():
        # A consented location image becomes the opening frame for the first
        # generated scene. Portrait uploads intentionally never take this path.
        files.append(("input_reference", (reference_image.name, reference_image.read_bytes(), "image/jpeg")))
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.post(
            "https://api.openai.com/v1/videos",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
        )
    if response.is_error:
        log.warning("Video teaser request failed: %s", response.text[:500])
        raise RuntimeError("The video provider could not start this teaser")
    job = response.json()
    if not job.get("id"):
        raise RuntimeError("The video provider did not return a render job")
    return job


async def wait_for_video_teaser(video_id: str) -> tuple[dict, bytes]:
    """Poll one provider job in the background and download only its completed MP4."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is unavailable")
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as http:
        for _ in range(72):  # At most twelve minutes; the request itself already succeeded.
            response = await http.get(f"https://api.openai.com/v1/videos/{video_id}", headers=headers)
            if response.is_error:
                raise RuntimeError("The video provider could not check this teaser")
            job = response.json()
            status = job.get("status")
            if status == "completed":
                content = await http.get(f"https://api.openai.com/v1/videos/{video_id}/content", headers=headers)
                if content.is_error or not content.content:
                    raise RuntimeError("The finished teaser could not be downloaded")
                return job, content.content
            if status == "failed":
                raise RuntimeError("The video provider could not make this teaser")
            await asyncio.sleep(10)
    raise RuntimeError("The teaser is still rendering. Please check again shortly.")
