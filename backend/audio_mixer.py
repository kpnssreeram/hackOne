"""Audio mixer — turns Nolan's production timeline into a real audio drama mix."""
from __future__ import annotations
import shutil, subprocess, tempfile
from pathlib import Path
import logging

log = logging.getLogger("nolan.mixer")


def _configure_ffmpeg() -> bool:
    """Point pydub at a bundled FFmpeg binary when the system lacks one."""
    try:
        from pydub import AudioSegment
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        AudioSegment.converter = ffmpeg
        return bool(ffmpeg)
    except Exception as exc:
        log.warning("No usable audio decoder: %s", exc)
        return False


def _atmosphere(description: str, duration_ms: int, kind: str):
    """Create modest, original procedural beds/cues — no fake file references."""
    from pydub import AudioSegment
    from pydub.generators import Sine, WhiteNoise

    desc = description.lower()
    duration_ms = max(duration_ms, 350)
    if kind == "music":
        # A restrained two-note tension bed; deliberately kept beneath dialogue.
        low = Sine(110).to_audio_segment(duration=duration_ms).apply_gain(-37)
        high = Sine(165 if "magic" not in desc else 220).to_audio_segment(duration=duration_ms).apply_gain(-42)
        return low.overlay(high).fade_in(800).fade_out(1200)
    if "wand" in desc or "magic" in desc or "spell" in desc:
        shimmer = Sine(880).to_audio_segment(duration=duration_ms).apply_gain(-21)
        return shimmer.overlay(Sine(1320).to_audio_segment(duration=duration_ms).apply_gain(-29)).fade_in(60).fade_out(300)
    if "door" in desc or "crash" in desc or "alarm" in desc:
        hit = WhiteNoise().to_audio_segment(duration=min(220, duration_ms)).low_pass_filter(700).apply_gain(-18)
        tail = Sine(95).to_audio_segment(duration=duration_ms).apply_gain(-33).fade_out(duration_ms)
        return hit.overlay(tail)
    if "footstep" in desc or "running" in desc:
        step = WhiteNoise().to_audio_segment(duration=80).low_pass_filter(450).apply_gain(-23)
        cue = AudioSegment.silent(duration=duration_ms)
        for offset in range(0, duration_ms, 240): cue = cue.overlay(step, position=offset)
        return cue
    # Default ambience: soft filtered noise, enough to create a listening space.
    return WhiteNoise().to_audio_segment(duration=duration_ms).low_pass_filter(900).apply_gain(-43).fade_in(600).fade_out(900)


def _decode_mp3(path: Path):
    """Decode with bundled ffmpeg without depending on a separate ffprobe."""
    from pydub import AudioSegment
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
        wav_path = Path(temp.name)
    try:
        subprocess.run([AudioSegment.converter, "-y", "-i", str(path), str(wav_path)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return AudioSegment.from_wav(wav_path)
    finally:
        wav_path.unlink(missing_ok=True)


def mix_timeline(timeline: list[dict], out_path: Path) -> Path:
    """Mix dialogue, original procedural ambience, music and cue effects to MP3."""
    if not _configure_ffmpeg():
        raise RuntimeError("Audio mixer is unavailable")

    from pydub import AudioSegment
    spoken = AudioSegment.empty()
    ambience_descriptions: list[str] = []
    music_descriptions: list[str] = []

    for entry in timeline:
        kind = entry.get("type")
        if kind == "ambience":
            ambience_descriptions.append(entry.get("description") or "atmosphere")
        elif kind == "music":
            music_descriptions.append(entry.get("description") or "unresolved score")
        elif kind == "dialogue" and entry.get("path"):
            path = Path(entry["path"])
            if path.exists():
                spoken += _decode_mp3(path) + AudioSegment.silent(duration=int(entry.get("pause_after", .45) * 1000))
        elif kind == "silence":
            spoken += AudioSegment.silent(duration=max(250, int(float(entry.get("duration", 1)) * 1000)))
        elif kind == "sfx":
            cue = _atmosphere(entry.get("description") or "cue", int(float(entry.get("duration", 1)) * 1000), "sfx")
            # Effects are an audible beat between lines, not a silent placeholder.
            spoken += cue + AudioSegment.silent(duration=180)

    if len(spoken) == 0:
        raise RuntimeError("No spoken audio was available to mix")

    # A Pocket-FM-style pilot needs breathing room. Preserve its spoken arc,
    # then finish with a short atmospheric cliffhanger tail when it is brief.
    target_ms = max(60_000, len(spoken) + 5_000)
    bed = _atmosphere(ambience_descriptions[0] if ambience_descriptions else "atmosphere", target_ms, "ambience")
    if music_descriptions:
        bed = bed.overlay(_atmosphere(music_descriptions[0], target_ms, "music"))
    mixed = bed.overlay(spoken, position=0)
    if len(mixed) < target_ms:
        mixed += bed[len(mixed):target_ms]
    mixed = mixed.normalize(headroom=1.5).fade_in(120).fade_out(1200)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mixed.export(out_path, format="mp3", bitrate="128k")
    log.info("Mixed real pilot → %s (%.1fs)", out_path, len(mixed) / 1000)
    return out_path
