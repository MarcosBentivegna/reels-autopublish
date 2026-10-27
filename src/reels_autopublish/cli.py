"""Command line entry point: `reels-autopublish <command>`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import load_config


def cmd_preflight(cfg, args) -> int:
    from . import preflight

    text, code = preflight.report(preflight.run(cfg, skip=set(args.skip or [])))
    print(text)
    return code


def cmd_drive_login(cfg, args) -> int:
    from . import drive

    drive.get_credentials(cfg, interactive=True)
    print(f"Token saved to {cfg.drive_token}")
    return 0


def cmd_upload(cfg, args) -> int:
    from . import drive

    paths = [Path(p) for p in args.files]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print(f"error: not found: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(json.dumps(drive.upload_and_publish(cfg, paths, args.folder), indent=2))
    return 0


def cmd_buffer_channels(cfg, args) -> int:
    from .buffer import BufferClient

    print(json.dumps(BufferClient(cfg).save_channels(), indent=2))
    return 0


def cmd_publish_reel(cfg, args) -> int:
    from .buffer import BufferClient

    text = Path(args.caption_file).read_text(encoding="utf-8").strip() if args.caption_file else args.caption
    if not text:
        print("error: pass --caption or --caption-file", file=sys.stderr)
        return 1
    results = BufferClient(cfg).publish_reel(
        text=text,
        video_url=args.video_url,
        youtube_title=args.title,
        tiktok_title=args.title,
        due_at=args.due_at,
        thumbnail_offset_ms=args.cover_ms,
        save_to_draft=args.draft,
        video_name=args.name,
        networks=tuple(args.networks),
    )
    print(json.dumps(results, indent=2))
    return 0


def cmd_mux(cfg, args) -> int:
    from . import audio

    track = audio.mux(cfg, Path(args.video), Path(args.out))
    print(f"Mixed {track.name} -> {args.out}")
    return 0


def cmd_cleanup(cfg, args) -> int:
    from . import cleanup

    plan = cleanup.run(cfg, dry_run=args.dry_run, use_drive=not args.local_only)
    print(f"{len(plan.days)} day folder(s), {len(plan.videos)} video(s), {len(plan.carousels)} carousel(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="reels-autopublish", description=__doc__)
    p.add_argument("--config", help="path to reels.toml (default: ./reels.toml or $REELS_CONFIG)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("preflight", help="check credentials, tools and state before a batch")
    s.add_argument("--skip", nargs="*", choices=["binaries", "disk", "tracks", "state", "drive", "buffer"])
    s.set_defaults(func=cmd_preflight)

    s = sub.add_parser("drive-login", help="authorize Google Drive once (opens a browser)")
    s.set_defaults(func=cmd_drive_login)

    s = sub.add_parser("upload", help="upload files to Drive; media gets a public direct link")
    s.add_argument("files", nargs="+")
    s.add_argument("--folder", help="Drive folder name (default: drive.video_folder)")
    s.set_defaults(func=cmd_upload)

    s = sub.add_parser("buffer-channels", help="save the connected Buffer channel ids")
    s.set_defaults(func=cmd_buffer_channels)

    s = sub.add_parser("publish-reel", help="schedule a reel on Instagram, TikTok and YouTube via Buffer")
    s.add_argument("--video-url", required=True, help="public URL of the .mp4 (see `upload`)")
    s.add_argument("--title", required=True, help="title for YouTube and TikTok")
    s.add_argument("--caption")
    s.add_argument("--caption-file")
    s.add_argument("--due-at", help="ISO 8601 UTC, e.g. 2026-11-02T18:00:00Z (default: now)")
    s.add_argument("--cover-ms", type=int, help="cover frame offset in ms (Instagram and TikTok)")
    s.add_argument("--name", help="local file name, for publish_log.csv")
    s.add_argument("--networks", nargs="+", default=["instagram", "tiktok", "youtube"],
                   choices=["instagram", "tiktok", "youtube"])
    s.add_argument("--draft", action="store_true", help="create as drafts that are never sent")
    s.set_defaults(func=cmd_publish_reel)

    s = sub.add_parser("mux", help="add a rotating background track to a silent video")
    s.add_argument("video")
    s.add_argument("out")
    s.set_defaults(func=cmd_mux)

    s = sub.add_parser("cleanup", help="delete published days locally and trash their Drive copies")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--local-only", action="store_true", help="do not touch Drive")
    s.set_defaults(func=cmd_cleanup)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(load_config(args.config), args)


if __name__ == "__main__":
    sys.exit(main())
