"""
Audio Mixer — assembles the final cinematic audio pilot.
Stitches TTS lines + silence gaps + SFX/ambience stubs.
Falls back gracefully if ffmpeg / pydub unavailable.
"""
from __future__ import annotations
import os
from pathlib import Path
import logging

log = logging.getLogger("nolan.mixer")


def _pydub_available() -> bool:
    try:
        from pydub import AudioSegment  # noqa: F401
        return True
    except ImportError:
        return False


def mix_timeline(timeline: list[dict], out_path: Path) -> Path:
    """
    Mix a timeline of {type, path?, duration?, description?} into one MP3.
    Returns path to the mixed file.
    """
    if not _pydub_available():
        log.warning("pydub not available — returning first dialogue track as pilot")
        for entry in timeline:
            if entry.get("path") and Path(entry["path"]).exists():
                import shutil
                shutil.copy(entry["path"], out_path)
                return out_path
        return out_path

    from pydub import AudioSegment

    combined = AudioSegment.empty()
    sfx_dir = Path(__file__).parent / "sfx"

    for entry in timeline:
        t = entry.get("type")

        if t == "dialogue" and entry.get("path"):
            p = Path(entry["path"])
            if p.exists():
                seg = AudioSegment.from_mp3(str(p))
                combined += seg
                # small gap after each line
                pause = int(entry.get("pause_after", 0.4) * 1000)
                combined += AudioSegment.silent(duration=pause)

        elif t == "silence":
            ms = int(float(entry.get("duration", 1.0)) * 1000)
            combined += AudioSegment.silent(duration=max(ms, 100))

        elif t in ("ambience", "sfx", "music"):
            # Look for a matching local SFX file by keyword
            desc = (entry.get("description") or "").lower()
            ms = int(float(entry.get("duration", 2.0)) * 1000)
            sfx_file = _find_sfx(sfx_dir, desc)
            if sfx_file:
                sfx_seg = AudioSegment.from_file(str(sfx_file))[:ms]
                sfx_seg = sfx_seg - 15  # duck -15dB
                # Overlay with last N ms of combined (or add as prefix)
                if len(combined) >= ms:
                    combined = combined.overlay(sfx_seg, position=len(combined) - ms)
                else:
                    combined = sfx_seg.overlay(combined)
            else:
                # No SFX file — just add silence placeholder
                combined += AudioSegment.silent(duration=min(ms, 2000))

    # Normalise and export
    combined = combined.normalize()
    combined.export(str(out_path), format="mp3", bitrate="128k")
    log.info("Mixed audio → %s (%.1fs)", out_path, len(combined) / 1000)
    return out_path


def _find_sfx(sfx_dir: Path, description: str) -> Path | None:
    if not sfx_dir.exists():
        return None
    keywords = description.split()
    for f in sfx_dir.iterdir():
        name = f.stem.lower()
        if any(kw in name for kw in keywords):
            return f
    return None
