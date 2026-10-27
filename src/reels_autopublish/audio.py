"""Background music for silent reels, rotating through a folder of tracks.

Picks a random track that was not used in the last N reels, trims it to the
video's real length (read with ffprobe, so reels of different lengths need no
constants), fades it in and out, and muxes it in as the only audio stream.

Every run is logged to audio_usage_log.csv. Instagram does not expose which
audio a post used, so that log is the only way to cross reach per track later.
"""
from __future__ import annotations

import csv
import datetime
import json
import random
import subprocess
from pathlib import Path

from .config import Config

AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".aac"}


def find_tracks(tracks_dir: Path) -> list[Path]:
    if not tracks_dir.is_dir():
        return []
    return sorted(p for p in tracks_dir.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES)


def load_recent(state_path: Path) -> list[str]:
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8")).get("last_used", [])
    return []


def pick_track(tracks: list[Path], recent: list[str], avoid_last: int, rng: random.Random | None = None) -> Path:
    """Avoids the last `avoid_last` tracks. If that leaves nothing (very few
    tracks), relaxes to avoiding only the last one, then to any track."""
    if not tracks:
        raise ValueError("no tracks to choose from")
    rng = rng or random.Random()
    for window in (avoid_last, 1, 0):
        blocked = set(recent[-window:]) if window else set()
        candidates = [t for t in tracks if t.name not in blocked]
        if candidates:
            return rng.choice(candidates)
    return rng.choice(tracks)


def remember(state_path: Path, track: Path, keep: int) -> None:
    recent = load_recent(state_path) + [track.name]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"last_used": recent[-max(keep, 1):]}, indent=2) + "\n", encoding="utf-8")


def log_usage(log_path: Path, video: Path, track: Path, total: int) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not log_path.exists()
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["date", "video", "track", "total_tracks"])
        writer.writerow([datetime.date.today().isoformat(), str(video), track.name, total])


def probe_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def ffmpeg_command(video: Path, track: Path, out: Path, duration: float, fade_in: float, fade_out: float) -> list[str]:
    fade_out_start = max(0.0, duration - fade_out)
    return [
        "ffmpeg", "-y",
        "-i", str(video),
        "-ss", "0", "-t", f"{duration:.3f}", "-i", str(track),
        "-filter_complex",
        f"[1:a]afade=t=in:st=0:d={fade_in},afade=t=out:st={fade_out_start:.3f}:d={fade_out}[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        str(out),
    ]


def mux(cfg: Config, video: Path, out: Path, rng: random.Random | None = None) -> Path:
    """Returns the track used. State and log are written only after ffmpeg
    succeeds, so a failed render does not count as a use."""
    tracks = find_tracks(cfg.tracks_dir)
    if not tracks:
        raise FileNotFoundError(f"no audio tracks in {cfg.tracks_dir}")
    track = pick_track(tracks, load_recent(cfg.audio_state), cfg.audio_avoid_last, rng)
    duration = probe_duration(video)
    subprocess.run(
        ffmpeg_command(video, track, out, duration, cfg.audio_fade_in, cfg.audio_fade_out),
        check=True, capture_output=True,
    )
    remember(cfg.audio_state, track, cfg.audio_avoid_last)
    log_usage(cfg.audio_log, out, track, len(tracks))
    return track
