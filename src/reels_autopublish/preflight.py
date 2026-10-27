"""Preflight: check everything the day's batch will need BEFORE generating
the first piece.

Without it, an expired credential only shows up at the publishing step, with
the day's content already rendered. Every check here is something that broke
for real at least once, not a defensive list:

- A Drive token that still refreshes can lack write permission. That only
  shows when writing, so the check uploads and deletes a probe file.
- Buffer channel ids change when an account is reconnected, and posts then
  fail with an unhelpful error. Saved ids are compared with the live ones.

Exit code: 0 if the batch can run (warnings do not block), 1 on any failure.
"""
from __future__ import annotations

import io
import json
import shutil
import socket
from dataclasses import dataclass

from .config import Config

OK, WARN, FAIL = "OK", "WARN", "FAIL"


@dataclass
class Result:
    level: str
    name: str
    detail: str = ""


def check_binaries(cfg: Config) -> list[Result]:
    out = []
    for binary in cfg.required_binaries:
        path = shutil.which(binary)
        out.append(Result(OK, binary, path) if path else Result(FAIL, binary, "not in PATH"))
    return out


def check_disk(cfg: Config) -> list[Result]:
    target = cfg.output_dir if cfg.output_dir.exists() else cfg.root
    free_gb = shutil.disk_usage(target).free / 1024**3
    if free_gb < cfg.min_free_gb:
        return [Result(FAIL, "disk", f"{free_gb:.1f} GB free, the day's videos will not fit")]
    if free_gb < cfg.warn_free_gb:
        return [Result(WARN, "disk", f"{free_gb:.1f} GB free")]
    return [Result(OK, "disk", f"{free_gb:.1f} GB free")]


def check_tracks(cfg: Config) -> list[Result]:
    from .audio import find_tracks

    tracks = find_tracks(cfg.tracks_dir)
    if not tracks:
        return [Result(FAIL, "audio tracks", f"none in {cfg.tracks_dir}")]
    return [Result(OK, "audio tracks", f"{len(tracks)} tracks")]


def check_state(cfg: Config) -> list[Result]:
    if not cfg.state_dir.is_dir():
        return [Result(WARN, "state", f"{cfg.state_dir} does not exist; rotations start from zero")]
    broken = []
    for path in sorted(cfg.state_dir.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            broken.append(f"{path.name}: {exc}")
    if broken:
        return [Result(FAIL, "state", "; ".join(broken))]
    return [Result(OK, "state", "all JSON files parse")]


def check_drive(cfg: Config) -> list[Result]:
    if not cfg.drive_credentials.exists():
        return [Result(FAIL, "drive", f"missing {cfg.drive_credentials.name}")]
    if not cfg.drive_token.exists():
        return [Result(FAIL, "drive", "no token.json; run `reels-autopublish drive-login` once")]
    try:
        from googleapiclient.http import MediaIoBaseUpload

        from . import drive

        service = drive.get_service(cfg, interactive=False)
        probe = service.files().create(
            body={"name": "_preflight_check.txt"},
            media_body=MediaIoBaseUpload(io.BytesIO(b"preflight"), mimetype="text/plain"),
            fields="id",
        ).execute()
    except Exception as exc:  # noqa: BLE001 -- any failure here blocks the batch
        # RefreshError carries the reason in args[0] followed by a raw dict;
        # str() of the whole tuple gets cut mid-dict and reads badly.
        reason = exc.args[0] if exc.args and isinstance(exc.args[0], str) else str(exc)
        return [Result(FAIL, "drive", f"{reason[:140]} -- delete token.json and run drive-login")]
    try:
        service.files().delete(fileId=probe["id"]).execute()
    except Exception as exc:  # noqa: BLE001
        return [Result(WARN, "drive", f"upload OK, could not delete probe {probe['id']}: {str(exc)[:80]}")]
    return [Result(OK, "drive", "refresh, test upload and delete OK")]


def check_buffer(cfg: Config, client=None) -> list[Result]:
    if not cfg.buffer_token.exists():
        return [Result(FAIL, "buffer", f"missing {cfg.buffer_token.name}")]
    if not cfg.buffer_channels.exists():
        return [Result(FAIL, "buffer", "missing channels.json; run `reels-autopublish buffer-channels`")]
    from .buffer import BufferClient

    client = client or BufferClient(cfg)
    try:
        live = {c["service"]: c["id"] for c in client.list_channels()}
    except Exception as exc:  # noqa: BLE001
        return [Result(FAIL, "buffer", f"auth failed: {str(exc)[:160]}")]
    saved = client.load_channels()
    mismatched = [svc for svc, cid in saved.items() if live.get(svc) != cid]
    if mismatched:
        return [Result(FAIL, "buffer", f"channel ids changed for {', '.join(mismatched)}; run buffer-channels")]
    return [Result(OK, "buffer", f"auth OK, channels: {', '.join(sorted(live))}")]


def run(cfg: Config, skip: set[str] | None = None) -> list[Result]:
    skip = skip or set()
    socket.setdefaulttimeout(45)
    checks = {
        "binaries": check_binaries,
        "disk": check_disk,
        "tracks": check_tracks,
        "state": check_state,
        "drive": check_drive,
        "buffer": check_buffer,
    }
    results: list[Result] = []
    for name, check in checks.items():
        if name in skip:
            results.append(Result(WARN, name, "skipped"))
        else:
            results.extend(check(cfg))
    return results


def report(results: list[Result]) -> tuple[str, int]:
    width = max((len(r.name) for r in results), default=0)
    lines = [f"  {r.level:4s}  {r.name.ljust(width)}  {r.detail}" for r in results]
    failures = [r for r in results if r.level == FAIL]
    warnings = [r for r in results if r.level == WARN]
    if failures:
        lines.append(f"\nPREFLIGHT: {len(failures)} failure(s). Do not generate anything until fixed.")
        return "\n".join(lines), 1
    lines.append(f"\nPREFLIGHT OK ({len(warnings)} warning(s)).")
    return "\n".join(lines), 0
