"""Retention: once a day's content is published, delete it locally and move
its Drive copies to the trash.

Expected layout: output/<YYYYMMDD>/videos/*.mp4 (+ .txt caption sidecars)
and output/<YYYYMMDD>/carousels/<slug>/.

Decides by the calendar date in the folder name, not by file age. The job
runs once a day (e.g. 04:00). With a rolling "older than 24 h" rule, a reel
rendered at 23:00 is only 5 hours old at the next run and survives an extra
day. Comparing folder dates with today has no such gap.
"""
from __future__ import annotations

import datetime
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import drive
from .config import Config


@dataclass
class Plan:
    days: list[Path] = field(default_factory=list)
    videos: list[Path] = field(default_factory=list)
    carousels: list[Path] = field(default_factory=list)


def expired_days(output_dir: Path, today: datetime.date) -> list[Path]:
    if not output_dir.is_dir():
        return []
    stamp = today.strftime("%Y%m%d")
    return sorted(
        p for p in output_dir.iterdir()
        if p.is_dir() and len(p.name) == 8 and p.name.isdigit() and p.name < stamp
    )


def build_plan(output_dir: Path, today: datetime.date) -> Plan:
    plan = Plan(days=expired_days(output_dir, today))
    for day in plan.days:
        plan.videos += sorted((day / "videos").glob("*.mp4")) if (day / "videos").is_dir() else []
        if (day / "carousels").is_dir():
            plan.carousels += sorted(p for p in (day / "carousels").iterdir() if p.is_dir())
    return plan


def run(cfg: Config, today: datetime.date | None = None, dry_run: bool = False, use_drive: bool = True,
        log=print) -> Plan:
    plan = build_plan(cfg.output_dir, today or datetime.date.today())
    if not plan.days:
        return plan

    service = video_folder = carousel_folder = None
    if use_drive and not dry_run:
        service = drive.get_service(cfg, interactive=False)
        video_folder = drive.find_folder(service, cfg.drive_video_folder)
        carousel_folder = drive.find_folder(service, cfg.drive_carousel_folder)

    prefix = "[dry-run] " if dry_run else ""
    for video in plan.videos:
        sidecar = video.with_suffix(".txt")
        log(f"{prefix}delete {video.relative_to(cfg.output_dir)}")
        if service:
            drive.trash_by_name(service, video_folder, video.name)
            drive.trash_by_name(service, video_folder, sidecar.name)
    for carousel in plan.carousels:
        log(f"{prefix}delete {carousel.relative_to(cfg.output_dir)}/")
        if service:
            drive.trash_folder(service, carousel_folder, carousel.name)

    if not dry_run:
        for day in plan.days:
            shutil.rmtree(day)
    return plan
