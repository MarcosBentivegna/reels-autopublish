"""Project configuration, read from a TOML file (`reels.toml` by default).

Every relative path in the file is resolved against the directory that holds
the config file, not the current working directory, so the same commands work
from cron/launchd jobs that start somewhere else.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_NAME = "reels.toml"
CONFIG_ENV_VAR = "REELS_CONFIG"


@dataclass
class Config:
    root: Path
    output_dir: Path
    state_dir: Path
    tracks_dir: Path
    secrets_dir: Path
    drive_video_folder: str = "reels"
    drive_carousel_folder: str = "carousels"
    drive_public_suffixes: tuple[str, ...] = (".mp4",)
    youtube_category_id: str = "22"
    audio_fade_in: float = 0.3
    audio_fade_out: float = 0.4
    audio_avoid_last: int = 2
    required_binaries: tuple[str, ...] = ("ffmpeg", "ffprobe")
    min_free_gb: float = 2.0
    warn_free_gb: float = 10.0
    extra: dict = field(default_factory=dict)

    # Secrets live in one folder that is gitignored as a whole, instead of
    # next to each script. One rule in .gitignore is harder to get wrong than
    # one per file.
    @property
    def drive_credentials(self) -> Path:
        return self.secrets_dir / "credentials.json"

    @property
    def drive_token(self) -> Path:
        return self.secrets_dir / "token.json"

    @property
    def buffer_token(self) -> Path:
        return self.secrets_dir / "buffer_token.txt"

    @property
    def buffer_channels(self) -> Path:
        return self.secrets_dir / "channels.json"

    @property
    def publish_log(self) -> Path:
        return self.state_dir / "publish_log.csv"

    @property
    def audio_state(self) -> Path:
        return self.state_dir / "audio_cycle.json"

    @property
    def audio_log(self) -> Path:
        return self.state_dir / "audio_usage_log.csv"


def find_config_path(explicit: str | os.PathLike | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.environ.get(CONFIG_ENV_VAR):
        return Path(os.environ[CONFIG_ENV_VAR]).expanduser().resolve()
    return (Path.cwd() / DEFAULT_CONFIG_NAME).resolve()


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Loads the config file. A missing file is not an error: every value has
    a default, so a bare project folder with the standard layout just works."""
    config_path = find_config_path(path)
    data: dict = {}
    if config_path.exists():
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent

    paths = data.get("paths", {})
    drive = data.get("drive", {})
    buffer = data.get("buffer", {})
    audio = data.get("audio", {})
    preflight = data.get("preflight", {})

    def resolve(key: str, default: str) -> Path:
        return (root / paths.get(key, default)).resolve()

    return Config(
        root=root,
        output_dir=resolve("output_dir", "output"),
        state_dir=resolve("state_dir", "state"),
        tracks_dir=resolve("tracks_dir", "tracks"),
        secrets_dir=resolve("secrets_dir", "secrets"),
        drive_video_folder=drive.get("video_folder", "reels"),
        drive_carousel_folder=drive.get("carousel_folder", "carousels"),
        drive_public_suffixes=tuple(s.lower() for s in drive.get("public_suffixes", [".mp4"])),
        youtube_category_id=str(buffer.get("youtube_category_id", "22")),
        audio_fade_in=float(audio.get("fade_in", 0.3)),
        audio_fade_out=float(audio.get("fade_out", 0.4)),
        audio_avoid_last=int(audio.get("avoid_last", 2)),
        required_binaries=tuple(preflight.get("binaries", ["ffmpeg", "ffprobe"])),
        min_free_gb=float(preflight.get("min_free_gb", 2)),
        warn_free_gb=float(preflight.get("warn_free_gb", 10)),
        extra={k: v for k, v in data.items() if k not in {"paths", "drive", "buffer", "audio", "preflight"}},
    )
